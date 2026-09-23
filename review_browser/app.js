// Manifesto Commitment Review Browser
// Single-file app: loads data.json, renders two-panel layout

const DIM_LABELS = { P: 'Prevention', T: 'Physical', I: 'Knowledge', R: 'Resilience', C: 'Consumption', CC: 'Constitutional' };
const DIMS = ['P', 'T', 'I', 'R', 'C', 'CC'];
// Short codes shown on the score chips; keys stay as the data's dimension codes.
const DIM_SHORT = { P: 'P', T: 'Ph', I: 'K', R: 'R', C: 'C', CC: 'CC' };

let DATA = null;
let currentDocIndex = -1;
let currentCommitmentIndex = -1;
let filteredCommitments = [];
let pdfDoc = null;
let pdfPages = [];             // {canvas, wrapper, textContent, viewport} per page
let pdfPageOffsets = [];
let suppressPdfScrollSync = false;

// Mode state
let currentMode = 'commitments';   // 'commitments' | 'nlp'
let selectedGroups = new Set();    // group keys currently toggled on
let NLP = null;                    // lazy-loaded {groups, hits}
let nlpLoadPromise = null;
let pendingNlpRedraw = false;      // set when iframe reloads while in NLP mode

// ── Data loading ──

async function loadData() {
  showLoading('Loading data...');
  try {
    const resp = await fetch('data.json');
    DATA = await resp.json();
    hideLoading();
    buildDocSelect();
    if (DATA.documents.length > 0) selectDocument(0);
  } catch (e) {
    document.getElementById('loading-message').textContent = `Error: ${e.message}`;
  }
}

function showLoading(msg) {
  document.getElementById('loading-message').textContent = msg;
  document.getElementById('loading-overlay').classList.remove('hidden');
}

function hideLoading() {
  document.getElementById('loading-overlay').classList.add('hidden');
}

// ── Document selector ──

let docByParty = new Map(); // partyName -> [{doc, index}, ...] sorted year desc

function buildDocSelect() {
  docByParty = new Map();
  DATA.documents.forEach((doc, i) => {
    const key = doc.partyName;
    if (!docByParty.has(key)) docByParty.set(key, []);
    docByParty.get(key).push({ doc, index: i });
  });
  for (const entries of docByParty.values()) {
    entries.sort((a, b) => b.doc.year - a.doc.year);
  }

  const partiesList = document.getElementById('doc-picker-parties');
  partiesList.innerHTML = '';
  const sortedParties = [...docByParty.keys()].sort((a, b) => a.localeCompare(b));

  for (const partyName of sortedParties) {
    const entries = docByParty.get(partyName);
    const row = document.createElement('div');
    row.className = 'picker-item picker-party';

    const label = document.createElement('span');
    label.textContent = partyName;
    row.appendChild(label);

    const count = document.createElement('span');
    count.className = 'picker-count';
    count.textContent = entries.length + ' \u25B6';
    row.appendChild(count);

    // Build flyout submenu - position next to the dropdown on hover
    const flyout = document.createElement('div');
    flyout.className = 'picker-flyout';
    row.addEventListener('mouseenter', () => {
      const dropdownRect = document.getElementById('doc-picker-dropdown').getBoundingClientRect();
      flyout.style.left = dropdownRect.right + 'px';
    });
    // Touch devices have no hover: tapping the party row toggles its flyout.
    // Checked at tap time so DevTools emulation / convertible laptops work.
    row.addEventListener('click', (e) => {
      if (!window.matchMedia('(hover: none)').matches) return;
      e.stopPropagation();
      const wasVisible = flyout.classList.contains('visible');
      document.querySelectorAll('.picker-flyout.visible').forEach(f => f.classList.remove('visible'));
      if (wasVisible) return;
      const dropdownRect = document.getElementById('doc-picker-dropdown').getBoundingClientRect();
      if (window.matchMedia('(max-width: 720px)').matches) {
        // CSS pins left/right; align with the dropdown vertically
        flyout.style.top = dropdownRect.top + 'px';
        flyout.style.maxHeight = (window.innerHeight - dropdownRect.top - 8) + 'px';
      } else {
        flyout.style.left = dropdownRect.right + 'px';
      }
      flyout.classList.add('visible');
    });
    for (const { doc, index } of entries) {
      const yearRow = document.createElement('div');
      yearRow.className = 'picker-item picker-year';
      yearRow.innerHTML = `<strong>${doc.year}</strong> <span class="picker-title">${escHtml(doc.title.slice(0, 45))}</span>`;
      const commitCount = document.createElement('span');
      commitCount.className = 'picker-count';
      commitCount.textContent = doc.nCommitments;
      yearRow.appendChild(commitCount);
      yearRow.addEventListener('click', (e) => {
        e.stopPropagation();
        selectDocument(index);
        closePicker();
      });
      flyout.appendChild(yearRow);
    }
    row.appendChild(flyout);
    partiesList.appendChild(row);
  }

  const btn = document.getElementById('doc-picker-btn');
  const dropdown = document.getElementById('doc-picker-dropdown');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const nowHidden = dropdown.classList.toggle('hidden');
    if (!nowHidden && window.matchMedia('(max-width: 720px)').matches) {
      // Wrapped toolbar height varies, so position below it dynamically
      const toolbarRect = document.getElementById('toolbar').getBoundingClientRect();
      dropdown.style.top = (toolbarRect.bottom + 4) + 'px';
      dropdown.style.maxHeight = (window.innerHeight - toolbarRect.bottom - 12) + 'px';
    } else {
      dropdown.style.top = '';
      dropdown.style.maxHeight = '';
    }
  });

  document.addEventListener('click', (e) => {
    if (!document.getElementById('doc-picker').contains(e.target)) {
      closePicker();
    }
  });
}

function closePicker() {
  document.getElementById('doc-picker-dropdown').classList.add('hidden');
  document.querySelectorAll('.picker-flyout.visible').forEach(f => f.classList.remove('visible'));
}

function updatePickerButton() {
  const doc = DATA.documents[currentDocIndex];
  document.getElementById('doc-picker-btn').textContent =
    `${doc.partyName} ${doc.year}`;
}

function selectDocument(index) {
  if (index < 0 || index >= DATA.documents.length) return;
  currentDocIndex = index;
  currentCommitmentIndex = -1;

  const doc = DATA.documents[index];
  updatePickerButton();
  updateDocInfo();

  // Clear searches when switching documents
  document.getElementById('search-input').value = '';
  document.getElementById('source-search-input').value = '';
  clearSourceSearch();

  applyFilters();
  renderCommitments();

  if (doc.format === 'pdf') {
    loadPdf(doc.path);
  } else {
    showTextSource(doc);
  }

  if (currentMode === 'commitments') {
    if (filteredCommitments.length > 0) selectCommitment(0);
  } else if (currentMode === 'nlp') {
    renderNlpPanel();
    scheduleNlpRedraw();
  }
}

function updateDocInfo() {
  const doc = DATA.documents[currentDocIndex];
  const info = document.getElementById('doc-info');
  if (currentMode === 'commitments') {
    info.textContent = `${doc.partyName} | ${doc.year} | ${doc.nCommitments} commitments`;
  } else {
    info.textContent = `${doc.partyName} | ${doc.year} | ${doc.title}`;
  }
}

// ── Filtering ──

function applyFilters() {
  const doc = DATA.documents[currentDocIndex];
  const hideAmbig = document.getElementById('filter-ambiguous').checked;
  const hideLow = document.getElementById('filter-low-trust').checked;
  const searchTerm = (document.getElementById('search-input').value || '').trim().toLowerCase();

  filteredCommitments = doc.commitments.filter(c => {
    if (hideAmbig && c.ambig) return false;
    if (hideLow && c.trust === 'low') return false;
    if (searchTerm) {
      const haystack = (c.text + ' ' + (c.quote || '')).toLowerCase();
      if (!haystack.includes(searchTerm)) return false;
    }
    return true;
  });

  document.getElementById('commitment-counter').textContent =
    `${filteredCommitments.length} / ${doc.nCommitments}`;
}

// ── Commitment rendering ──

function renderCommitments() {
  const list = document.getElementById('commitments-list');
  list.innerHTML = '';

  filteredCommitments.forEach((c, i) => {
    const card = document.createElement('div');
    card.className = 'commitment-card';
    if (c.ambig) card.classList.add('ambiguous');
    if (c.trust === 'low') card.classList.add('low-trust');
    card.dataset.index = i;

    card.innerHTML = `
      <div class="commitment-text">${escHtml(c.text)}</div>
      <div class="score-row">
        ${DIMS.map(d => `<span class="score-chip" data-dim="${d}" data-val="${c.scores[d]}">${DIM_SHORT[d]}:${c.scores[d]}</span>`).join('')}
        <span class="confidence-tag">${c.conf.toFixed(2)}</span>
        <span class="trust-tag ${c.trust}">${c.trust}</span>
      </div>
      <div class="commitment-detail">${buildDetail(c)}</div>
    `;

    card.addEventListener('click', () => {
      if (currentCommitmentIndex === i) {
        // Already selected - toggle expand
        card.classList.toggle('expanded');
      } else {
        // Select and expand
        document.querySelectorAll('.commitment-card.expanded').forEach(c => c.classList.remove('expanded'));
        card.classList.add('expanded');
        // On mobile, show the source panel BEFORE selecting: scroll-to-highlight
        // is a no-op while the panel is display:none
        setMobileView('source');
        selectCommitment(i);
      }
    });

    list.appendChild(card);
  });
}

function buildDetail(c) {
  let html = '';

  if (c.rationales) {
    html += '<div class="detail-section"><div class="detail-label">Score rationales</div>';
    for (const d of DIMS) {
      if (c.rationales[d]) {
        html += `<div class="rationale-item"><span class="rationale-dim" data-dim="${d}">${DIM_LABELS[d]} (${c.scores[d]})</span><span>${escHtml(c.rationales[d])}</span></div>`;
      }
    }
    html += '</div>';
  }

  if (c.quote && c.quote !== c.text) {
    html += `<div class="detail-section"><div class="detail-label">Supporting quote</div><div class="quote-text">${escHtml(c.quote)}</div></div>`;
  }

  if (c.ambig && c.ambigNote) {
    html += `<div class="detail-section"><div class="detail-label">Ambiguity note</div><div>${escHtml(c.ambigNote)}</div></div>`;
  }

  return html;
}

// ── Commitment selection ──

function selectCommitment(index) {
  if (index < 0 || index >= filteredCommitments.length) return;
  currentCommitmentIndex = index;

  const cards = document.querySelectorAll('.commitment-card');
  cards.forEach(c => c.classList.remove('active'));
  if (cards[index]) {
    cards[index].classList.add('active');
    cards[index].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  const c = filteredCommitments[index];
  const doc = DATA.documents[currentDocIndex];

  if (doc.format === 'pdf') {
    scrollPdfToCommitment(c, doc);
  } else {
    scrollTextToCommitment(c);
  }
}

// ── PDF source (continuous scroll with text search highlight) ──

async function loadPdf(path) {
  const pdfContainer = document.getElementById('pdf-container');
  const htmlContainer = document.getElementById('html-container');
  const textContainer = document.getElementById('text-container');
  pdfContainer.classList.remove('hidden');
  htmlContainer.classList.add('hidden');
  textContainer.classList.add('hidden');

  const pdfScroll = document.getElementById('pdf-scroll');
  pdfScroll.innerHTML = '';
  pdfPages = [];
  pdfPageOffsets = [];
  pdfDoc = null;

  if (!window.pdfjsLib) {
    await new Promise(resolve => window.addEventListener('pdfjsReady', resolve, { once: true }));
  }
  const pdfjsLib = window.pdfjsLib;

  pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.9.155/pdf.worker.min.mjs';

  showLoading('Loading PDF...');

  try {
    pdfDoc = await pdfjsLib.getDocument(path).promise;
    document.getElementById('pdf-page-info').textContent = `${pdfDoc.numPages} pages`;

    const containerWidth = pdfContainer.clientWidth - 24;

    for (let i = 1; i <= pdfDoc.numPages; i++) {
      const page = await pdfDoc.getPage(i);
      const viewport = page.getViewport({ scale: 1 });
      const scale = containerWidth / viewport.width;
      const scaledViewport = page.getViewport({ scale });

      // Wrapper div for positioning highlights over the canvas
      const wrapper = document.createElement('div');
      wrapper.className = 'pdf-page-wrapper';

      const canvas = document.createElement('canvas');
      canvas.className = 'pdf-page-canvas';
      canvas.width = scaledViewport.width;
      canvas.height = scaledViewport.height;
      canvas.dataset.page = i;

      const ctx = canvas.getContext('2d');
      await page.render({ canvasContext: ctx, viewport: scaledViewport }).promise;

      // Get text content for search highlighting
      const textContent = await page.getTextContent();

      wrapper.appendChild(canvas);
      pdfScroll.appendChild(wrapper);
      pdfPages.push({ canvas, wrapper, textContent, viewport: scaledViewport });
    }

    computePageOffsets();
    hideLoading();

    if (currentMode === 'nlp' && pendingNlpRedraw) {
      pendingNlpRedraw = false;
      redrawNlpHighlights();
    }
  } catch (e) {
    hideLoading();
    document.getElementById('source-header').textContent = `PDF error: ${e.message}`;
  }
}

function computePageOffsets() {
  pdfPageOffsets = pdfPages.map(p => p.wrapper.offsetTop);
}

function getVisiblePdfPage() {
  const container = document.getElementById('pdf-scroll');
  const scrollMid = container.scrollTop + container.clientHeight / 3;
  let page = 1;
  for (let i = 0; i < pdfPageOffsets.length; i++) {
    if (pdfPageOffsets[i] <= scrollMid) {
      page = i + 1;
    } else {
      break;
    }
  }
  return page;
}

function charPosToPage(charPos, doc) {
  if (!doc.pageBreaks) return 1;
  let page = 1;
  for (let i = 0; i < doc.pageBreaks.length; i++) {
    if (doc.pageBreaks[i] <= charPos) {
      page = i + 1;
    } else {
      break;
    }
  }
  return page;
}

function scrollPdfToCommitment(commitment, doc) {
  if (!pdfDoc || pdfPages.length === 0) return;
  const page = charPosToPage(commitment.qStart, doc);
  const pageIndex = Math.min(page - 1, pdfPages.length - 1);
  const wrapper = pdfPages[pageIndex].wrapper;

  suppressPdfScrollSync = true;
  wrapper.scrollIntoView({ block: 'start', behavior: 'smooth' });
  setTimeout(() => { suppressPdfScrollSync = false; }, 600);

  document.getElementById('pdf-page-info').textContent = `Page ${page} / ${pdfDoc.numPages}`;

  // Highlight the quote text on the PDF page
  highlightQuoteOnPdf(commitment, page);
}

// ── PDF text highlight ──

function clearPdfHighlights() {
  document.querySelectorAll('.pdf-highlight').forEach(el => el.remove());
}

function normalizeForSearch(str) {
  // Collapse whitespace and lowercase for fuzzy matching
  return str.replace(/\s+/g, ' ').trim().toLowerCase();
}

function highlightQuoteOnPdf(commitment, targetPage) {
  clearPdfHighlights();

  // Search the target page and its neighbors (quote might span pages or page mapping might be off by 1)
  const pagesToSearch = [targetPage - 1, targetPage, targetPage + 1]
    .filter(p => p >= 1 && p <= pdfPages.length);

  const searchText = normalizeForSearch(commitment.quote || commitment.text);
  if (!searchText) return;

  for (const pageNum of pagesToSearch) {
    const pageData = pdfPages[pageNum - 1];
    const { textContent, viewport, wrapper, canvas } = pageData;
    const items = textContent.items;
    if (!items.length) continue;

    // Build full page text from items, tracking each item's position in the concatenated string
    let fullText = '';
    const itemMeta = []; // {start, end, item} in fullText
    for (const item of items) {
      const start = fullText.length;
      fullText += item.str;
      itemMeta.push({ start, end: fullText.length, item });
      // Items often lack trailing spaces; add one to avoid words merging
      if (item.str.length > 0 && !item.hasEOL) {
        fullText += ' ';
      }
    }

    const normalizedFull = normalizeForSearch(fullText);

    // Try to find the quote. If the full quote doesn't match, try progressively
    // shorter prefixes (the quote may be truncated at page boundary).
    let matchIdx = -1;
    let matchLen = searchText.length;

    // Try full match first
    matchIdx = normalizedFull.indexOf(searchText);

    // If no full match, try the first 60 chars (enough to locate it)
    if (matchIdx === -1 && searchText.length > 60) {
      const prefix = searchText.slice(0, 60);
      matchIdx = normalizedFull.indexOf(prefix);
      if (matchIdx >= 0) matchLen = prefix.length;
    }

    // If still no match, try the first 30 chars
    if (matchIdx === -1 && searchText.length > 30) {
      const prefix = searchText.slice(0, 30);
      matchIdx = normalizedFull.indexOf(prefix);
      if (matchIdx >= 0) matchLen = prefix.length;
    }

    if (matchIdx === -1) continue;

    // Map the match range in normalizedFull back to original fullText character positions.
    // Since normalization only collapses whitespace, we can do a forward walk.
    const origRange = mapNormalizedRange(fullText, normalizedFull, matchIdx, matchLen);
    if (!origRange) continue;

    // Find all text items that overlap with the match range
    const matchStart = origRange.start;
    const matchEnd = origRange.end;
    const matchingItems = itemMeta.filter(m => m.end > matchStart && m.start < matchEnd);
    if (!matchingItems.length) continue;

    // Group matching items by approximate Y position (line grouping)
    const lines = groupItemsByLine(matchingItems, viewport);

    // Draw highlight rectangles
    const scaleX = canvas.width / viewport.width;
    const scaleY = canvas.height / viewport.height;

    for (const line of lines) {
      const rect = computeLineBounds(line, viewport);
      const highlight = document.createElement('div');
      highlight.className = 'pdf-highlight';
      highlight.style.left = (rect.left / viewport.width * 100) + '%';
      highlight.style.top = (rect.top / viewport.height * 100) + '%';
      highlight.style.width = (rect.width / viewport.width * 100) + '%';
      highlight.style.height = (rect.height / viewport.height * 100) + '%';
      wrapper.appendChild(highlight);
    }

    // If we found a match, scroll the highlight into view (within the wrapper's page)
    const firstHighlight = wrapper.querySelector('.pdf-highlight');
    if (firstHighlight) {
      requestAnimationFrame(() => {
        const container = document.getElementById('pdf-scroll');
        const highlightTop = wrapper.offsetTop + firstHighlight.offsetTop;
        const scrollTarget = highlightTop - container.clientHeight / 3;
        suppressPdfScrollSync = true;
        container.scrollTo({ top: scrollTarget, behavior: 'smooth' });
        setTimeout(() => { suppressPdfScrollSync = false; }, 600);
      });
    }

    break; // Found match on this page, stop searching
  }
}

function mapNormalizedRange(original, normalized, normStart, normLen) {
  // Walk both strings to map normalized offsets back to original offsets
  let oi = 0; // original index
  let ni = 0; // normalized index
  let origStart = -1;
  let origEnd = -1;

  const origLower = original.toLowerCase();

  while (oi < original.length && ni < normalized.length) {
    if (ni === normStart) origStart = oi;
    if (ni === normStart + normLen) { origEnd = oi; break; }

    const oc = origLower[oi];
    const nc = normalized[ni];

    if (oc === nc) {
      oi++;
      ni++;
    } else if (/\s/.test(oc)) {
      // Original has extra whitespace that was collapsed
      oi++;
    } else {
      // Shouldn't happen, but advance both
      oi++;
      ni++;
    }
  }

  if (origStart >= 0 && origEnd < 0) origEnd = oi;
  if (origStart < 0) return null;
  return { start: origStart, end: origEnd };
}

function groupItemsByLine(matchingItems, viewport) {
  // Convert item positions to viewport coords and group by Y
  const positioned = matchingItems.map(({ item }) => {
    const tx = item.transform[4];
    const ty = item.transform[5];
    const fontSize = Math.sqrt(item.transform[0] ** 2 + item.transform[1] ** 2);
    // PDF coords: origin bottom-left. viewport.convertToViewportPoint flips Y.
    const [vx, vy] = viewport.convertToViewportPoint(tx, ty);
    const [vx2] = viewport.convertToViewportPoint(tx + (item.width || 0), ty);
    return { left: Math.min(vx, vx2), right: Math.max(vx, vx2), top: vy - fontSize * viewport.scale, bottom: vy, fontSize };
  });

  // Group by approximate Y (items within ~fontSize of each other are on the same line)
  const lines = [];
  for (const pos of positioned) {
    let added = false;
    for (const line of lines) {
      if (Math.abs(pos.top - line[0].top) < pos.fontSize * 0.5) {
        line.push(pos);
        added = true;
        break;
      }
    }
    if (!added) lines.push([pos]);
  }
  return lines;
}

function computeLineBounds(lineItems, viewport) {
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const item of lineItems) {
    left = Math.min(left, item.left);
    top = Math.min(top, item.top);
    right = Math.max(right, item.right);
    bottom = Math.max(bottom, item.bottom);
  }
  // Add some padding
  const pad = 3;
  return {
    left: Math.max(0, left - pad),
    top: Math.max(0, top - pad),
    width: right - left + pad * 2,
    height: bottom - top + pad * 2,
  };
}

// PDF scroll -> sync commitments panel
function onPdfScroll() {
  if (suppressPdfScrollSync || !pdfDoc || !DATA) return;
  const doc = DATA.documents[currentDocIndex];
  if (!doc || doc.format !== 'pdf' || !doc.pageBreaks) return;

  computePageOffsets();
  const visiblePage = getVisiblePdfPage();
  document.getElementById('pdf-page-info').textContent = `Page ${visiblePage} / ${pdfDoc.numPages}`;

  const pageCharStart = doc.pageBreaks[visiblePage - 1] || 0;
  const pageCharEnd = (visiblePage < doc.pageBreaks.length) ? doc.pageBreaks[visiblePage] : Infinity;

  let bestIndex = -1;
  for (let i = 0; i < filteredCommitments.length; i++) {
    const c = filteredCommitments[i];
    if (c.qStart >= pageCharStart && c.qStart < pageCharEnd) {
      bestIndex = i;
      break;
    }
  }

  if (bestIndex >= 0 && bestIndex !== currentCommitmentIndex) {
    currentCommitmentIndex = bestIndex;
    const cards = document.querySelectorAll('.commitment-card');
    cards.forEach(c => c.classList.remove('active'));
    if (cards[bestIndex]) {
      cards[bestIndex].classList.add('active');
      cards[bestIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }
}

// ── Text source ──

function showTextSource(doc) {
  const pdfContainer = document.getElementById('pdf-container');
  const htmlContainer = document.getElementById('html-container');
  const textContainer = document.getElementById('text-container');
  pdfContainer.classList.add('hidden');
  htmlContainer.classList.add('hidden');
  textContainer.classList.add('hidden');
  pdfDoc = null;
  pdfPages = [];

  // Store fullText for search and commitment-highlight offset lookups
  window._currentFullText = doc.fullText || '';

  // Load original HTML file in iframe
  const iframe = document.getElementById('html-frame');
  htmlContainer.classList.remove('hidden');
  iframe.src = doc.path;

  // Inject cleanup styles once loaded, then flush any pending highlight
  iframe.onload = () => {
    const idoc = iframe.contentDocument;
    if (!idoc) return;

    // Remove Wayback Machine toolbar/banners
    const wbTop = idoc.getElementById('wm-ipp-base') || idoc.getElementById('wm-ipp');
    if (wbTop) wbTop.remove();
    const wbBanner = idoc.querySelector('.wb-autocomplete-suggestions');
    if (wbBanner) wbBanner.remove();

    // Add a style for our highlights
    const style = idoc.createElement('style');
    let nlpCss = '';
    if (NLP) nlpCss = buildNlpIframeCss(NLP.groups);
    style.textContent = `
      .commitment-highlight {
        background: rgba(74, 125, 255, 0.25) !important;
        outline: 2px solid rgba(74, 125, 255, 0.6);
        border-radius: 2px;
      }
      .source-search-hit {
        background: rgba(255, 200, 50, 0.35) !important;
        border-radius: 2px;
      }
      .source-search-hit.current {
        background: rgba(255, 200, 50, 0.7) !important;
      }
      ${nlpCss}
    `;
    idoc.head.appendChild(style);

    // Flush pending highlights for whichever mode we're in
    if (currentMode === 'commitments' && pendingCommitmentHighlight) {
      const c = pendingCommitmentHighlight;
      pendingCommitmentHighlight = null;
      doHighlightInIframe(idoc, c);
    }
    if (currentMode === 'nlp' && pendingNlpRedraw) {
      pendingNlpRedraw = false;
      redrawNlpHighlights();
    }
  };
}

let pendingCommitmentHighlight = null;

function scrollTextToCommitment(commitment) {
  const iframe = document.getElementById('html-frame');
  const idoc = iframe.contentDocument;

  // If iframe hasn't loaded yet, queue the highlight
  if (!idoc || !idoc.body || !idoc.body.innerText) {
    pendingCommitmentHighlight = commitment;
    return;
  }

  doHighlightInIframe(idoc, commitment);
}

function doHighlightInIframe(idoc, commitment) {
  // Clear previous highlights
  idoc.querySelectorAll('.commitment-highlight').forEach(el => {
    const parent = el.parentNode;
    if (parent) {
      parent.replaceChild(idoc.createTextNode(el.textContent), el);
      parent.normalize();
    }
  });

  // Search for the quote text in the iframe body
  const quoteText = commitment.quote || commitment.text;
  if (!quoteText) return;

  const found = findAndHighlightText(idoc.body, quoteText, 'commitment-highlight');
  if (found) {
    found.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}

// Collapse whitespace for fuzzy matching
function collapseWS(str) {
  return str.replace(/\s+/g, ' ').trim().toLowerCase();
}

// Walk the DOM tree text nodes to find and wrap matching text.
// Uses whitespace-normalized fuzzy matching with fallback to shorter fragments.
function findAndHighlightText(root, searchText, className) {
  const odoc = root.ownerDocument;
  const walker = odoc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  // Build concatenated raw text with node mappings
  let rawFull = '';
  const nodeMap = []; // {node, start, end} in rawFull
  for (const node of textNodes) {
    const start = rawFull.length;
    rawFull += node.textContent;
    nodeMap.push({ node, start, end: rawFull.length });
  }

  // Build a parallel whitespace-collapsed version with index mapping back to raw
  const { collapsed, rawIndices } = buildCollapsedMap(rawFull);

  // Try matching progressively shorter fragments
  const needle = collapseWS(searchText);
  let matchStart = -1;
  let matchLen = 0;

  // Full match
  matchStart = collapsed.indexOf(needle);
  if (matchStart >= 0) {
    matchLen = needle.length;
  }

  // First 80 chars
  if (matchStart < 0 && needle.length > 80) {
    const prefix = needle.slice(0, 80);
    matchStart = collapsed.indexOf(prefix);
    if (matchStart >= 0) matchLen = prefix.length;
  }

  // First 40 chars
  if (matchStart < 0 && needle.length > 40) {
    const prefix = needle.slice(0, 40);
    matchStart = collapsed.indexOf(prefix);
    if (matchStart >= 0) matchLen = prefix.length;
  }

  // Last resort: longest single phrase (split on common delimiters)
  if (matchStart < 0) {
    const phrases = needle.split(/[;,\-\(\)]/).map(s => s.trim()).filter(s => s.length > 15);
    phrases.sort((a, b) => b.length - a.length);
    for (const phrase of phrases) {
      matchStart = collapsed.indexOf(phrase);
      if (matchStart >= 0) { matchLen = phrase.length; break; }
    }
  }

  if (matchStart < 0) return null;

  // Map collapsed match range back to raw text range
  const rawStart = rawIndices[matchStart];
  const rawEnd = rawIndices[Math.min(matchStart + matchLen, rawIndices.length - 1)];

  // Find overlapping text nodes and wrap them
  let firstMark = null;
  for (const entry of nodeMap) {
    if (entry.end <= rawStart || entry.start >= rawEnd) continue;

    const node = entry.node;
    if (!node.parentNode) continue;
    const nodeStart = Math.max(0, rawStart - entry.start);
    const nodeEnd = Math.min(node.textContent.length, rawEnd - entry.start);

    const before = node.textContent.slice(0, nodeStart);
    const match = node.textContent.slice(nodeStart, nodeEnd);
    const after = node.textContent.slice(nodeEnd);

    const parent = node.parentNode;
    const frag = odoc.createDocumentFragment();
    if (before) frag.appendChild(odoc.createTextNode(before));
    const mark = odoc.createElement('span');
    mark.className = className;
    mark.textContent = match;
    frag.appendChild(mark);
    if (after) frag.appendChild(odoc.createTextNode(after));
    parent.replaceChild(frag, node);

    if (!firstMark) firstMark = mark;
  }

  return firstMark;
}

// Build a whitespace-collapsed string and a mapping from each collapsed index
// back to the corresponding index in the raw string.
function buildCollapsedMap(raw) {
  const lower = raw.toLowerCase();
  let collapsed = '';
  const rawIndices = []; // rawIndices[i] = index in raw for collapsed[i]
  let inSpace = false;

  for (let i = 0; i < lower.length; i++) {
    const ch = lower[i];
    if (/\s/.test(ch)) {
      if (!inSpace && collapsed.length > 0) {
        collapsed += ' ';
        rawIndices.push(i);
        inSpace = true;
      }
    } else {
      collapsed += ch;
      rawIndices.push(i);
      inSpace = false;
    }
  }

  // Trim trailing space
  if (collapsed.endsWith(' ')) {
    collapsed = collapsed.slice(0, -1);
    rawIndices.pop();
  }

  // One extra entry so rawIndices[matchStart + matchLen] is valid
  rawIndices.push(raw.length);

  return { collapsed, rawIndices };
}

// ── Resizable divider ──

function setupDivider() {
  const divider = document.getElementById('divider');
  const panel = document.getElementById('right-panel');
  let dragging = false;

  divider.addEventListener('mousedown', (e) => {
    dragging = true;
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const newWidth = window.innerWidth - e.clientX;
    panel.style.width = Math.max(280, Math.min(800, newWidth)) + 'px';
  });

  document.addEventListener('mouseup', () => { dragging = false; });
}

// ── Mobile Source / List view switcher ──
// data-mobile-view only has effect inside the max-width media query,
// so calling this on desktop is a no-op visually.

function setMobileView(view) {
  if (view !== 'source' && view !== 'list') return;
  document.getElementById('main').dataset.mobileView = view;
  document.querySelectorAll('#view-switcher .view-btn').forEach(btn => {
    const active = btn.dataset.view === view;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
}

function setupViewSwitcher() {
  document.querySelectorAll('#view-switcher .view-btn').forEach(btn => {
    btn.addEventListener('click', () => setMobileView(btn.dataset.view));
  });
}

// ── NLP (Long-term Language) mode ──

const NLP_HITS_PATH = 'nlp_hits.json';
const NLP_MAX_HITS_PER_GROUP = 1500;  // perf cap per doc-group

function setMode(next) {
  if (next !== 'commitments' && next !== 'nlp') return;
  if (next === currentMode) return;
  currentMode = next;

  document.querySelectorAll('.mode-btn').forEach(btn => {
    const active = btn.dataset.mode === next;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.commitments-only').forEach(el => {
    el.hidden = next !== 'commitments';
  });
  document.querySelectorAll('.nlp-only').forEach(el => {
    el.hidden = next !== 'nlp';
  });
  document.getElementById('commitments-panel').hidden = next !== 'commitments';
  document.getElementById('nlp-panel').hidden = next !== 'nlp';

  updateDocInfo();

  if (next === 'commitments') {
    clearNlpHighlights();
    if (currentCommitmentIndex >= 0 && filteredCommitments[currentCommitmentIndex]) {
      // Restore commitment highlight
      selectCommitment(currentCommitmentIndex);
    } else if (filteredCommitments.length > 0) {
      selectCommitment(0);
    }
  } else {
    clearCommitmentHighlights();
    ensureNlpLoaded().then(() => {
      renderNlpPanel();
      scheduleNlpRedraw();
    }).catch(err => {
      const list = document.getElementById('nlp-groups-list');
      list.innerHTML = `<div class="nlp-error">Could not load word-group data: ${escHtml(err.message || String(err))}</div>`;
    });
  }
}

function ensureNlpLoaded() {
  if (NLP) return Promise.resolve(NLP);
  if (nlpLoadPromise) return nlpLoadPromise;
  const list = document.getElementById('nlp-groups-list');
  list.innerHTML = '<div class="nlp-loading">Loading word-group data...</div>';
  nlpLoadPromise = fetch(NLP_HITS_PATH)
    .then(resp => {
      if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${NLP_HITS_PATH}`);
      return resp.json();
    })
    .then(payload => {
      NLP = payload;
      injectNlpPdfStyles();
      injectNlpCssIntoCurrentIframe();
      return payload;
    })
    .catch(err => {
      nlpLoadPromise = null;
      throw err;
    });
  return nlpLoadPromise;
}

function renderNlpPanel() {
  if (!NLP) return;
  const doc = DATA.documents[currentDocIndex];
  const docHits = NLP.hits[doc.docId];
  const list = document.getElementById('nlp-groups-list');
  list.innerHTML = '';

  for (const group of NLP.groups) {
    const count = docHits ? (docHits._counts[group.key] || 0) : 0;
    const row = document.createElement('label');
    row.className = 'nlp-group-row';
    if (count === 0) row.classList.add('empty');

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'nlp-group-checkbox';
    cb.dataset.groupKey = group.key;
    cb.checked = selectedGroups.has(group.key);
    cb.disabled = count === 0;
    cb.addEventListener('change', () => {
      if (cb.checked) selectedGroups.add(group.key);
      else selectedGroups.delete(group.key);
      // On mobile, show the source panel before drawing so PDF overlay
      // positions are measurable (display:none panels have zero layout)
      if (cb.checked) setMobileView('source');
      redrawNlpHighlights();
      updateNlpDocCounter();
    });

    const swatch = document.createElement('span');
    swatch.className = 'nlp-swatch';
    swatch.style.background = group.colour;

    const label = document.createElement('span');
    label.className = 'nlp-group-label';
    label.textContent = group.label;

    const countEl = document.createElement('span');
    countEl.className = 'nlp-group-count';
    countEl.textContent = count.toLocaleString();

    const tip = document.createElement('span');
    tip.className = 'nlp-group-examples';
    tip.textContent = group.examples.slice(0, 10).join(', ');

    row.appendChild(cb);
    row.appendChild(swatch);
    row.appendChild(label);
    row.appendChild(countEl);
    row.appendChild(tip);
    list.appendChild(row);
  }

  updateNlpDocCounter();
}

function updateNlpDocCounter() {
  const counter = document.getElementById('nlp-doc-counter');
  if (!counter) return;
  if (!NLP || currentDocIndex < 0) {
    counter.textContent = '';
    return;
  }
  const doc = DATA.documents[currentDocIndex];
  const docHits = NLP.hits[doc.docId];
  if (!docHits) { counter.textContent = ''; return; }
  if (selectedGroups.size === 0) {
    counter.textContent = 'Select a group to highlight matches';
    return;
  }
  let total = 0;
  for (const group of selectedGroups) {
    total += docHits._counts[group] || 0;
  }
  counter.textContent = `${total.toLocaleString()} highlighted`;
}

function clearNlpSelection() {
  if (selectedGroups.size === 0) return;
  selectedGroups.clear();
  document.querySelectorAll('.nlp-group-checkbox').forEach(cb => { cb.checked = false; });
  clearNlpHighlights();
  updateNlpDocCounter();
}

function scheduleNlpRedraw() {
  if (currentMode !== 'nlp') return;
  const doc = DATA.documents[currentDocIndex];
  if (!doc) return;
  if (doc.format === 'pdf') {
    if (pdfPages.length === 0) {
      pendingNlpRedraw = true;
      return;
    }
    redrawNlpHighlights();
  } else {
    // iframe: wait for onload to flush pending redraw
    const iframe = document.getElementById('html-frame');
    if (!iframe.contentDocument || !iframe.contentDocument.body) {
      pendingNlpRedraw = true;
      return;
    }
    redrawNlpHighlights();
  }
}

function redrawNlpHighlights() {
  clearNlpHighlights();
  if (currentMode !== 'nlp' || !NLP) return;
  if (selectedGroups.size === 0) return;
  const doc = DATA.documents[currentDocIndex];
  const docHits = NLP.hits[doc.docId];
  if (!docHits) return;

  const hitsByGroup = {};
  for (const key of selectedGroups) {
    const hits = docHits[key] || [];
    if (hits.length > NLP_MAX_HITS_PER_GROUP) {
      hitsByGroup[key] = { hits: hits.slice(0, NLP_MAX_HITS_PER_GROUP), capped: true };
    } else {
      hitsByGroup[key] = { hits, capped: false };
    }
  }

  if (doc.format === 'pdf') {
    drawNlpHighlightsOnPdf(doc, hitsByGroup);
  } else {
    drawNlpHighlightsInIframe(doc, hitsByGroup);
  }
}

function clearNlpHighlights() {
  // PDF overlays
  document.querySelectorAll('.nlp-hit-pdf').forEach(el => el.remove());
  // Iframe spans
  try {
    const idoc = document.getElementById('html-frame').contentDocument;
    if (idoc) {
      idoc.querySelectorAll('.nlp-hit').forEach(el => {
        const parent = el.parentNode;
        if (parent) {
          parent.replaceChild(idoc.createTextNode(el.textContent), el);
          parent.normalize();
        }
      });
    }
  } catch (e) { /* ignore */ }
}

function clearCommitmentHighlights() {
  document.querySelectorAll('.pdf-highlight').forEach(el => el.remove());
  try {
    const idoc = document.getElementById('html-frame').contentDocument;
    if (idoc) {
      idoc.querySelectorAll('.commitment-highlight').forEach(el => {
        const parent = el.parentNode;
        if (parent) {
          parent.replaceChild(idoc.createTextNode(el.textContent), el);
          parent.normalize();
        }
      });
    }
  } catch (e) { /* ignore */ }
}

// PDF NLP highlighter: bucket hits by page, search normalized page text for
// each distinct matched token, draw one overlay per occurrence per group.
function drawNlpHighlightsOnPdf(doc, hitsByGroup) {
  if (!pdfPages.length) return;

  // Bucket: pageIndex -> groupKey -> Set of distinct matched tokens (lowercased)
  const byPage = new Map();
  for (const [groupKey, { hits }] of Object.entries(hitsByGroup)) {
    for (const hit of hits) {
      const page = charPosToPage(hit.s, doc);
      const pageIndex = Math.min(page - 1, pdfPages.length - 1);
      if (!byPage.has(pageIndex)) byPage.set(pageIndex, new Map());
      const groups = byPage.get(pageIndex);
      if (!groups.has(groupKey)) groups.set(groupKey, new Set());
      groups.get(groupKey).add(hit.t.toLowerCase().replace(/\s+/g, ' '));
    }
  }

  for (const [pageIndex, groups] of byPage) {
    drawNlpHitsOnPdfPage(pageIndex, groups);
  }
}

function drawNlpHitsOnPdfPage(pageIndex, groups) {
  const pageData = pdfPages[pageIndex];
  if (!pageData) return;
  const { textContent, viewport, wrapper } = pageData;
  const items = textContent.items;
  if (!items.length) return;

  let fullText = '';
  const itemMeta = [];
  for (const item of items) {
    const start = fullText.length;
    fullText += item.str;
    itemMeta.push({ start, end: fullText.length, item });
    if (item.str.length > 0 && !item.hasEOL) fullText += ' ';
  }
  const normalizedFull = normalizeForSearch(fullText);

  // Stack composite classes when the same text range is claimed by multiple groups
  const drawnByRange = new Map(); // "start:end" -> [divs]

  for (const [groupKey, tokenSet] of groups) {
    for (const token of tokenSet) {
      let pos = 0;
      while (true) {
        const idx = normalizedFull.indexOf(token, pos);
        if (idx === -1) break;
        const before = idx > 0 ? normalizedFull[idx - 1] : '';
        const after = idx + token.length < normalizedFull.length ? normalizedFull[idx + token.length] : '';
        if (isWordChar(before) || isWordChar(after)) { pos = idx + 1; continue; }

        const origRange = mapNormalizedRange(fullText, normalizedFull, idx, token.length);
        if (origRange) {
          const key = `${origRange.start}:${origRange.end}`;
          const existing = drawnByRange.get(key);
          const cls = `nlp-hit-pdf--${groupKey.replace(/_/g, '-')}`;
          if (existing) {
            existing.forEach(el => el.classList.add(cls));
          } else {
            const drawn = drawTightNlpOverlay(itemMeta, origRange, viewport, wrapper, cls);
            if (drawn.length) drawnByRange.set(key, drawn);
          }
        }
        pos = idx + 1;
      }
    }
  }
}

// Compute tight per-match overlay rects. For matches confined to a single text
// item (most single-word hits), estimate the rect using character ratios within
// the item. For multi-item matches, fall back to per-item bounds.
function drawTightNlpOverlay(itemMeta, origRange, viewport, wrapper, cls) {
  const drawn = [];
  const matching = itemMeta.filter(m => m.end > origRange.start && m.start < origRange.end);
  if (!matching.length) return drawn;

  for (const entry of matching) {
    const item = entry.item;
    if (!item.str.length || !item.width) continue;
    const itemStart = entry.start;
    const itemEnd = entry.end;
    const localStart = Math.max(0, origRange.start - itemStart);
    const localEnd = Math.min(item.str.length, origRange.end - itemStart);
    if (localEnd <= localStart) continue;

    const ratioLeft = localStart / item.str.length;
    const ratioRight = localEnd / item.str.length;
    const tx = item.transform[4];
    const ty = item.transform[5];
    const fontSize = Math.sqrt(item.transform[0] ** 2 + item.transform[1] ** 2);

    // Left/right edges in PDF coords then to viewport
    const leftPdf = tx + ratioLeft * item.width;
    const rightPdf = tx + ratioRight * item.width;
    const [vxLeft, vyBaseline] = viewport.convertToViewportPoint(leftPdf, ty);
    const [vxRight] = viewport.convertToViewportPoint(rightPdf, ty);
    const left = Math.min(vxLeft, vxRight);
    const right = Math.max(vxLeft, vxRight);
    const height = fontSize * viewport.scale;
    const top = vyBaseline - height;
    const width = right - left;

    const el = document.createElement('div');
    el.className = `nlp-hit-pdf ${cls}`;
    el.style.left = (left / viewport.width * 100) + '%';
    el.style.top = (top / viewport.height * 100) + '%';
    el.style.width = (width / viewport.width * 100) + '%';
    el.style.height = (height / viewport.height * 100) + '%';
    wrapper.appendChild(el);
    drawn.push(el);
  }

  return drawn;
}

function isWordChar(ch) {
  return /[a-z0-9_]/i.test(ch);
}

// Iframe NLP highlighter: collect all hit ranges, merge overlaps, wrap each
// merged range once with a composite class list.
function drawNlpHighlightsInIframe(doc, hitsByGroup) {
  const iframe = document.getElementById('html-frame');
  const idoc = iframe.contentDocument;
  if (!idoc || !idoc.body) return;

  // Collect all distinct tokens per group
  const tokensByGroup = new Map();
  for (const [groupKey, { hits }] of Object.entries(hitsByGroup)) {
    const set = new Set();
    for (const hit of hits) {
      set.add(hit.t.toLowerCase().replace(/\s+/g, ' '));
    }
    tokensByGroup.set(groupKey, set);
  }

  // Build collapsed text map of iframe body
  const walker = idoc.createTreeWalker(idoc.body, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  let rawFull = '';
  const nodeMap = [];
  for (const node of textNodes) {
    const start = rawFull.length;
    rawFull += node.textContent;
    nodeMap.push({ node, start, end: rawFull.length });
  }
  const { collapsed, rawIndices } = buildCollapsedMap(rawFull);

  // Find all match ranges on the collapsed text; tag each with its group
  // Intervals: {start, end} in raw text, plus set of groupKeys
  const intervals = [];
  for (const [groupKey, tokens] of tokensByGroup) {
    for (const token of tokens) {
      let pos = 0;
      while (true) {
        const idx = collapsed.indexOf(token, pos);
        if (idx === -1) break;
        const before = idx > 0 ? collapsed[idx - 1] : '';
        const after = idx + token.length < collapsed.length ? collapsed[idx + token.length] : '';
        if (!isWordChar(before) && !isWordChar(after)) {
          const rawStart = rawIndices[idx];
          const rawEnd = rawIndices[Math.min(idx + token.length, rawIndices.length - 1)];
          intervals.push({ start: rawStart, end: rawEnd, groupKey });
        }
        pos = idx + 1;
      }
    }
  }

  if (!intervals.length) return;

  // Merge overlapping/identical ranges into {start, end, groups: Set}
  intervals.sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [];
  for (const iv of intervals) {
    if (merged.length && iv.start < merged[merged.length - 1].end) {
      // Overlap: extend range, union groups
      const last = merged[merged.length - 1];
      if (iv.start === last.start && iv.end === last.end) {
        last.groups.add(iv.groupKey);
      } else {
        // Non-identical overlap - split into separate spans by taking the later hit's boundary.
        // Simplest: keep the first and drop the overlapping second.
        continue;
      }
    } else {
      merged.push({ start: iv.start, end: iv.end, groups: new Set([iv.groupKey]) });
    }
  }

  // Wrap in reverse so DOM mutations don't shift earlier offsets
  for (let i = merged.length - 1; i >= 0; i--) {
    const range = merged[i];
    const classList = ['nlp-hit'];
    for (const g of range.groups) classList.push(`nlp-hit--${g.replace(/_/g, '-')}`);
    wrapRangeInNodeMap(idoc, nodeMap, range.start, range.end, classList);
  }
}

function wrapRangeInNodeMap(idoc, nodeMap, rawStart, rawEnd, classList) {
  for (let n = nodeMap.length - 1; n >= 0; n--) {
    const entry = nodeMap[n];
    if (entry.end <= rawStart || entry.start >= rawEnd) continue;

    const node = entry.node;
    if (!node.parentNode) continue;
    const nodeStart = Math.max(0, rawStart - entry.start);
    const nodeEnd = Math.min(node.textContent.length, rawEnd - entry.start);

    const before = node.textContent.slice(0, nodeStart);
    const match = node.textContent.slice(nodeStart, nodeEnd);
    const after = node.textContent.slice(nodeEnd);

    const parent = node.parentNode;
    const frag = idoc.createDocumentFragment();
    if (before) frag.appendChild(idoc.createTextNode(before));
    const mark = idoc.createElement('span');
    mark.className = classList.join(' ');
    mark.textContent = match;
    frag.appendChild(mark);
    if (after) frag.appendChild(idoc.createTextNode(after));
    parent.replaceChild(frag, node);
  }
}

function buildNlpIframeCss(groups) {
  const rules = [];
  for (const group of groups) {
    const cls = `nlp-hit--${group.key.replace(/_/g, '-')}`;
    rules.push(`.${cls} { background: ${hexToRgba(group.colour, 0.35)} !important; }`);
  }
  return `
    .nlp-hit {
      border-radius: 2px;
      padding: 0 1px;
    }
    ${rules.join('\n    ')}
  `;
}

function injectNlpCssIntoCurrentIframe() {
  if (!NLP) return;
  try {
    const idoc = document.getElementById('html-frame').contentDocument;
    if (!idoc || !idoc.head) return;
    if (idoc.getElementById('nlp-iframe-styles')) return;
    const style = idoc.createElement('style');
    style.id = 'nlp-iframe-styles';
    style.textContent = buildNlpIframeCss(NLP.groups);
    idoc.head.appendChild(style);
  } catch (e) { /* ignore */ }
}

function injectNlpPdfStyles() {
  if (document.getElementById('nlp-pdf-styles')) return;
  if (!NLP) return;
  const style = document.createElement('style');
  style.id = 'nlp-pdf-styles';
  const rules = [];
  for (const group of NLP.groups) {
    const cls = `nlp-hit-pdf--${group.key.replace(/_/g, '-')}`;
    rules.push(`.${cls} { background: ${hexToRgba(group.colour, 0.35)}; }`);
  }
  style.textContent = `
    .nlp-hit-pdf {
      position: absolute;
      pointer-events: none;
      mix-blend-mode: multiply;
      border-radius: 2px;
    }
    ${rules.join('\n    ')}
  `;
  document.head.appendChild(style);
}

function hexToRgba(hex, alpha) {
  const m = hex.replace('#', '');
  const r = parseInt(m.slice(0, 2), 16);
  const g = parseInt(m.slice(2, 4), 16);
  const b = parseInt(m.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// ── Keyboard navigation ──

function setupKeyboard() {
  document.addEventListener('keydown', (e) => {
    const searchInput = document.getElementById('search-input');

    // Escape clears search and blurs
    if (e.key === 'Escape' && e.target === searchInput) {
      searchInput.value = '';
      searchInput.blur();
      refilter();
      return;
    }

    // / focuses search from anywhere
    if (e.key === '/' && e.target !== searchInput) {
      e.preventDefault();
      searchInput.focus();
      return;
    }

    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

    switch (e.key) {
      case 'j':
      case 'ArrowDown':
        if (currentMode !== 'commitments') break;
        e.preventDefault();
        selectCommitment(currentCommitmentIndex + 1);
        break;
      case 'k':
      case 'ArrowUp':
        if (currentMode !== 'commitments') break;
        e.preventDefault();
        selectCommitment(currentCommitmentIndex - 1);
        break;
      case '[':
        e.preventDefault();
        selectDocument(currentDocIndex - 1);
        break;
      case ']':
        e.preventDefault();
        selectDocument(currentDocIndex + 1);
        break;
      case 'Enter':
        e.preventDefault();
        toggleExpand();
        break;
    }
  });
}

function toggleExpand() {
  const cards = document.querySelectorAll('.commitment-card');
  if (cards[currentCommitmentIndex]) {
    cards[currentCommitmentIndex].classList.toggle('expanded');
  }
}

// ── Document navigation ──

function setupDocNav() {
  document.getElementById('prev-doc').addEventListener('click', () => selectDocument(currentDocIndex - 1));
  document.getElementById('next-doc').addEventListener('click', () => selectDocument(currentDocIndex + 1));
}

// ── Filters ──

function refilter() {
  applyFilters();
  renderCommitments();
  if (filteredCommitments.length > 0) selectCommitment(0);
}

function setupFilters() {
  document.getElementById('filter-ambiguous').addEventListener('change', refilter);
  document.getElementById('filter-low-trust').addEventListener('change', refilter);

  let searchTimer = null;
  document.getElementById('search-input').addEventListener('input', () => {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(refilter, 150);
  });
}

// ── PDF scroll listener ──

function setupPdfScroll() {
  const pdfScroll = document.getElementById('pdf-scroll');
  let scrollTimer = null;
  pdfScroll.addEventListener('scroll', () => {
    if (scrollTimer) clearTimeout(scrollTimer);
    scrollTimer = setTimeout(onPdfScroll, 150);
  });
}

// ── Source text search ──

let sourceSearchHits = [];   // for text docs: [{start, end}], for PDFs: [{pageIndex, rects}]
let sourceSearchCurrent = -1;

function setupSourceSearch() {
  let timer = null;
  const input = document.getElementById('source-search-input');
  input.addEventListener('input', () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => runSourceSearch(input.value), 200);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      navigateSourceSearch(e.shiftKey ? -1 : 1);
    }
    if (e.key === 'Escape') {
      input.value = '';
      input.blur();
      clearSourceSearch();
    }
  });
  document.getElementById('source-search-prev').addEventListener('click', () => navigateSourceSearch(-1));
  document.getElementById('source-search-next').addEventListener('click', () => navigateSourceSearch(1));
}

function clearSourceSearch() {
  sourceSearchHits = [];
  sourceSearchCurrent = -1;
  document.getElementById('source-search-info').textContent = '';
  // Clear PDF search highlights
  document.querySelectorAll('.pdf-search-highlight').forEach(el => el.remove());
  // Clear iframe search highlights
  try {
    const idoc = document.getElementById('html-frame').contentDocument;
    if (idoc) {
      idoc.querySelectorAll('.source-search-hit').forEach(el => {
        const parent = el.parentNode;
        parent.replaceChild(idoc.createTextNode(el.textContent), el);
        parent.normalize();
      });
    }
  } catch (e) { /* ignore */ }
}

function runSourceSearch(query) {
  clearSourceSearch();
  const term = query.trim().toLowerCase();
  if (!term || !DATA) return;

  const doc = DATA.documents[currentDocIndex];
  if (doc.format === 'pdf') {
    runPdfSourceSearch(term);
  } else {
    runHtmlSourceSearch(term);
  }
}

function runHtmlSourceSearch(term) {
  try {
    const idoc = document.getElementById('html-frame').contentDocument;
    if (!idoc || !idoc.body) return;

    // Walk text nodes to find all occurrences
    const walker = idoc.createTreeWalker(idoc.body, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    let fullText = '';
    const nodeMap = [];
    for (const node of textNodes) {
      const start = fullText.length;
      fullText += node.textContent;
      nodeMap.push({ node, start, end: fullText.length });
    }

    const lower = fullText.toLowerCase();
    const hits = [];
    let pos = 0;
    while (true) {
      const idx = lower.indexOf(term, pos);
      if (idx === -1) break;
      hits.push({ start: idx, end: idx + term.length });
      pos = idx + 1;
    }

    if (!hits.length) {
      document.getElementById('source-search-info').textContent = '0 results';
      return;
    }

    // Wrap matches in spans (process in reverse to avoid offset shifts)
    for (let h = hits.length - 1; h >= 0; h--) {
      const hit = hits[h];
      for (let n = nodeMap.length - 1; n >= 0; n--) {
        const entry = nodeMap[n];
        if (entry.end <= hit.start || entry.start >= hit.end) continue;
        // This node is stale if we already split it - re-read
      }
    }

    // Simpler approach: use iframe's window.find or mark all at once
    // Walk again fresh, mark all hits by rebuilding
    const walker2 = idoc.createTreeWalker(idoc.body, NodeFilter.SHOW_TEXT);
    const nodes2 = [];
    while (walker2.nextNode()) nodes2.push(walker2.currentNode);

    let fullText2 = '';
    const nodeMap2 = [];
    for (const node of nodes2) {
      const start = fullText2.length;
      fullText2 += node.textContent;
      nodeMap2.push({ node, start, end: fullText2.length });
    }

    // Process hits in reverse order so DOM mutations don't shift offsets
    const marks = [];
    for (let h = hits.length - 1; h >= 0; h--) {
      const hit = hits[h];
      for (let n = nodeMap2.length - 1; n >= 0; n--) {
        const entry = nodeMap2[n];
        if (entry.end <= hit.start || entry.start >= hit.end) continue;

        const node = entry.node;
        if (!node.parentNode) continue;

        const nodeStart = Math.max(0, hit.start - entry.start);
        const nodeEnd = Math.min(node.textContent.length, hit.end - entry.start);

        const before = node.textContent.slice(0, nodeStart);
        const match = node.textContent.slice(nodeStart, nodeEnd);
        const after = node.textContent.slice(nodeEnd);

        const parent = node.parentNode;
        const frag = idoc.createDocumentFragment();
        if (before) frag.appendChild(idoc.createTextNode(before));
        const mark = idoc.createElement('span');
        mark.className = 'source-search-hit';
        mark.dataset.hitIndex = h;
        mark.textContent = match;
        frag.appendChild(mark);
        if (after) frag.appendChild(idoc.createTextNode(after));
        parent.replaceChild(frag, node);

        if (!marks[h]) marks[h] = mark;
      }
    }

    sourceSearchHits = hits.map((hit, i) => ({ index: i }));
    sourceSearchCurrent = 0;
    updateHtmlSearchCurrent();
  } catch (e) {
    document.getElementById('source-search-info').textContent = 'search error';
  }
}

function updateHtmlSearchCurrent() {
  const info = document.getElementById('source-search-info');
  info.textContent = `${sourceSearchCurrent + 1} / ${sourceSearchHits.length}`;
  try {
    const idoc = document.getElementById('html-frame').contentDocument;
    if (!idoc) return;
    idoc.querySelectorAll('.source-search-hit').forEach(m => m.classList.remove('current'));
    const current = idoc.querySelectorAll(`.source-search-hit[data-hit-index="${sourceSearchCurrent}"]`);
    current.forEach(m => m.classList.add('current'));
    if (current.length) {
      current[0].scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  } catch (e) { /* ignore */ }
}

function runPdfSourceSearch(term) {
  if (!pdfDoc || !pdfPages.length) return;

  const hits = [];
  for (let pi = 0; pi < pdfPages.length; pi++) {
    const { textContent, viewport, wrapper } = pdfPages[pi];
    const items = textContent.items;
    if (!items.length) continue;

    let fullText = '';
    const itemMeta = [];
    for (const item of items) {
      const start = fullText.length;
      fullText += item.str;
      itemMeta.push({ start, end: fullText.length, item });
      if (item.str.length > 0 && !item.hasEOL) fullText += ' ';
    }

    const lower = fullText.toLowerCase();
    let pos = 0;
    while (true) {
      const idx = lower.indexOf(term, pos);
      if (idx === -1) break;
      const matchEnd = idx + term.length;
      const matchingItems = itemMeta.filter(m => m.end > idx && m.start < matchEnd);
      if (matchingItems.length) {
        const lines = groupItemsByLine(matchingItems, viewport);
        const rects = lines.map(line => computeLineBounds(line, viewport));
        hits.push({ pageIndex: pi, rects });

        // Draw highlights
        for (const rect of rects) {
          const el = document.createElement('div');
          el.className = 'pdf-search-highlight';
          el.style.left = (rect.left / viewport.width * 100) + '%';
          el.style.top = (rect.top / viewport.height * 100) + '%';
          el.style.width = (rect.width / viewport.width * 100) + '%';
          el.style.height = (rect.height / viewport.height * 100) + '%';
          el.dataset.hitIndex = hits.length - 1;
          wrapper.appendChild(el);
        }
      }
      pos = idx + 1;
    }
  }

  sourceSearchHits = hits;
  if (!hits.length) {
    document.getElementById('source-search-info').textContent = '0 results';
    return;
  }

  sourceSearchCurrent = 0;
  updatePdfSearchCurrent();
}

function updatePdfSearchCurrent() {
  const info = document.getElementById('source-search-info');
  info.textContent = `${sourceSearchCurrent + 1} / ${sourceSearchHits.length}`;

  document.querySelectorAll('.pdf-search-highlight').forEach(el => el.classList.remove('current'));
  const currentEls = document.querySelectorAll(`.pdf-search-highlight[data-hit-index="${sourceSearchCurrent}"]`);
  currentEls.forEach(el => el.classList.add('current'));

  // Scroll to current hit
  if (currentEls.length) {
    const hit = sourceSearchHits[sourceSearchCurrent];
    const wrapper = pdfPages[hit.pageIndex].wrapper;
    const container = document.getElementById('pdf-scroll');
    const elTop = wrapper.offsetTop + currentEls[0].offsetTop;
    suppressPdfScrollSync = true;
    container.scrollTo({ top: elTop - container.clientHeight / 3, behavior: 'smooth' });
    setTimeout(() => { suppressPdfScrollSync = false; }, 600);
  }
}

function navigateSourceSearch(direction) {
  if (!sourceSearchHits.length) return;
  sourceSearchCurrent = (sourceSearchCurrent + direction + sourceSearchHits.length) % sourceSearchHits.length;
  const doc = DATA.documents[currentDocIndex];
  if (doc.format === 'pdf') {
    updatePdfSearchCurrent();
  } else {
    updateHtmlSearchCurrent();
  }
}

// ── Utility ──

function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ── Init ──

setupDivider();
setupViewSwitcher();
setupKeyboard();
setupDocNav();
setupFilters();
setupPdfScroll();
setupSourceSearch();
setupModeToggle();
loadData();

function setupModeToggle() {
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => setMode(btn.dataset.mode));
  });
  const clearBtn = document.getElementById('nlp-clear-all');
  if (clearBtn) clearBtn.addEventListener('click', clearNlpSelection);
}
