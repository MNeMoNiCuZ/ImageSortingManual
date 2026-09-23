"use strict";

/* ------------------------------------------------------------------ util */
const $ = (id) => document.getElementById(id);
const el = (tag, cls) => { const n = document.createElement(tag); if (cls) n.className = cls; return n; };

let state = null;
let env = { platform: "", home: "", sort_orders: [], image_fits: [],
            file_actions: [], apply_modes: [], thumb_ratios: [], card_layouts: [],
            native_dialogs: false, config_file: "" };

const ASPECTS = { vertical: 9 / 16, horizontal: 16 / 9, square: 1 };
let imageToken = 0;

/* =============================================== zoom / pan state */
const zoomState = {
  level: 1.0,
  panX: 0,
  panY: 0,
};
let baseImgW = 0;
let baseImgH = 0;
const ZOOM_MIN = 0.10;
const ZOOM_MAX = 10.0;
const ZOOM_STEP = 0.10;
let zoomIsPanning = false;
let zoomPanStart = { x: 0, y: 0 };

function zoomReset() {
  zoomState.level = 1.0;
  zoomState.panX = 0;
  zoomState.panY = 0;
  applyZoom();
}

function zoomIn() {
  changeZoom(1);
}

function zoomOut() {
  changeZoom(-1);
}

function changeZoom(direction) {
  const step = ZOOM_STEP * 100;
  const percent = Math.round(zoomState.level * 100);
  const tick = direction > 0 ? Math.floor(percent / step) + 1 : Math.ceil(percent / step) - 1;
  zoomState.level = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, tick * step / 100));
  applyZoom();
}

function zoomBaseSize(viewer) {
  const style = getComputedStyle(viewer);
  const width = viewer.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const height = viewer.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  if (viewer.classList.contains("fit-cover")) return { width, height };
  const scale = Math.min(1, width / baseImgW, height / baseImgH);
  return { width: baseImgW * scale, height: baseImgH * scale };
}

function applyZoom() {
  requestAnimationFrame(() => {
    if (!baseImgW || !baseImgH) return;
    const img = $("main-image");
    if (!img || img.hidden) return;
    const viewer = $("viewer");
    const vw = viewer.clientWidth;
    const vh = viewer.clientHeight;
    if (vw <= 0 || vh <= 0) return;
    const z = zoomState.level;
    const base = zoomBaseSize(viewer);
    if (base.width <= 0 || base.height <= 0) return;
    const imgW = base.width * z;
    const imgH = base.height * z;
    // Keep half the image visible on each axis, or half the viewer when zoomed larger.
    const maxPanX = Math.max(imgW, vw) / 2;
    const maxPanY = Math.max(imgH, vh) / 2;
    zoomState.panX = Math.max(-maxPanX, Math.min(maxPanX, zoomState.panX));
    zoomState.panY = Math.max(-maxPanY, Math.min(maxPanY, zoomState.panY));

    if (z === 1.0 && zoomState.panX === 0 && zoomState.panY === 0) {
      viewer.classList.remove("zoomed");
      img.style.position = "";
      img.style.left = "";
      img.style.top = "";
      img.style.transform = "";
      img.style.transformOrigin = "";
      img.style.maxWidth = "";
      img.style.maxHeight = "";
      img.style.width = "";
      img.style.height = "";
      img.style.objectFit = "";
      img.style.cursor = "";
      img.style.transition = "";
      updateZoomUI();
      return;
    }

    viewer.classList.add("zoomed");
    img.style.maxWidth = "none";
    img.style.maxHeight = "none";
    img.style.width = `${base.width}px`;
    img.style.height = `${base.height}px`;
    img.style.position = "absolute";
    img.style.left = "0";
    img.style.top = "0";
    img.style.transition = "none";
    img.style.cursor = zoomIsPanning ? "grabbing" : "grab";

    const tx = Math.round((vw - imgW) / 2 + zoomState.panX);
    const ty = Math.round((vh - imgH) / 2 + zoomState.panY);
    img.style.transform = `translate(${tx}px, ${ty}px) scale(${z})`;
    img.style.transformOrigin = "0 0";

    updateZoomUI();
  });
}

function updateZoomUI() {
  const pct = Math.round(zoomState.level * 100);
  const levelEl = $("zoom-level");
  if (levelEl) {
    levelEl.textContent = pct + "%";
  }
}

async function api(path, options) {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (data && data.error) toast(data.error, true);
  else if (!res.ok) toast(`Request failed (${res.status})`, true);
  return data;
}

const post = (path, body) => api(path, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

const put = (path, body) => api(path, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

let toastTimer = null;
function scheduleToastHide() {
  clearTimeout(toastTimer);
  const node = $("toast");
  if (node.matches(":hover, :focus")) return;
  toastTimer = setTimeout(() => { node.hidden = true; }, node.classList.contains("error") ? 5200 : 3000);
}
$("toast").addEventListener("pointerenter", () => clearTimeout(toastTimer));
$("toast").addEventListener("pointerdown", () => clearTimeout(toastTimer));
$("toast").addEventListener("focus", () => clearTimeout(toastTimer));
$("toast").addEventListener("pointerleave", scheduleToastHide);
$("toast").addEventListener("blur", scheduleToastHide);
function toast(message, isError) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", !!isError);
  node.hidden = false;
  scheduleToastHide();
}

/* --------------------------------------------------------------- hotkeys */
/** Normalise a keyboard event into a stable, displayable hotkey string. */
function hotkeyFromEvent(event) {
  const key = event.key;
  if (["Shift", "Control", "Alt", "Meta"].includes(key)) return "";
  const parts = [];
  if (event.ctrlKey) parts.push("Ctrl");
  if (event.altKey) parts.push("Alt");
  if (event.metaKey) parts.push("Meta");
  // Shift is only a modifier for non-printable keys; for letters and symbols
  // the browser has already folded it into event.key.
  if (event.shiftKey && key.length > 1) parts.push("Shift");

  let base;
  if (key === " ") base = "Space";
  else if (key.length === 1) base = key.toUpperCase();
  else base = key;

  if (event.code && event.code.startsWith("Numpad")) base = "Num" + base;
  parts.push(base);
  return parts.join("+");
}

const matchesHotkey = (event, hotkey) =>
  !!hotkey && hotkeyFromEvent(event).toLowerCase() === hotkey.toLowerCase();

/* --------------------------------------------------------------- render */
function render(next) {
  if (!next) return;
  state = next;
  if (!pointerDrag) {
    document.querySelectorAll(".dragging").forEach((n) => n.classList.remove("dragging"));
  }
  applyConfigToChrome();
  renderViewer();
  renderFilmstrip();
  renderCards();
  renderStatus();
  fitHeader();
}

const aspect = () => ASPECTS[state.config.thumb_ratio] || ASPECTS.vertical;

function applyConfigToChrome() {
  const config = state.config;
  const root = document.documentElement.style;
  if (!dragging) {
    root.setProperty("--strip", `${config.filmstrip_size}px`);
    root.setProperty("--dock", `${config.dock_height}px`);
  }
  root.setProperty("--tile", `${config.card_thumb_size}px`);
  root.setProperty("--thumb-ar", String(aspect()));
  $("layout").classList.toggle("no-strip", !config.show_filmstrip);
  $("layout").classList.toggle("full-strip", config.full_height_strip);
  const viewer = $("viewer");
  const wasZoomed = viewer.classList.contains("zoomed");
  viewer.classList.toggle("fit-cover", config.image_fit === "cover");
  viewer.classList.toggle("fit-actual", config.image_fit === "actual");
  if (config.image_fit === "actual" && wasZoomed) {
    zoomReset();
  }
}

function renderViewer() {
  const image = $("main-image");
  const empty = $("empty-state");
  const current = state.current;

  if (current) {
    const token = ++imageToken;
    const url = `/api/image/${current.index}?v=${Date.now()}`;
    const loader = new Image();
    loader.onload = () => {
      if (token === imageToken) {
        image.src = url;
        image.hidden = false;
        baseImgW = loader.naturalWidth;
        baseImgH = loader.naturalHeight;
        applyZoom();
      }
    };
    loader.onerror = () => { if (token === imageToken) image.hidden = true; };
    loader.src = url;
    empty.hidden = true;
    image.alt = current.name;
    if (image.dataset.index !== String(current.index)) {
      image.dataset.index = String(current.index);
      zoomState.level = 1.0;
      zoomState.panX = 0;
      zoomState.panY = 0;
      if (!image.dataset.draggable) {
        image.dataset.draggable = "1";
        makeImageDraggable(image, current.index);
      }
    }

    $("info-name").textContent = current.name;
    $("info-name").title = current.path;
    $("info-dims").textContent = current.width ? `${current.width}×${current.height}` : "";
    $("info-size").textContent = current.size || "";
    const chips = $("info-sidecars");
    chips.replaceChildren();
    current.sidecars.forEach((ext) => {
      const chip = el("span", "chip");
      chip.textContent = ext;
      chips.append(chip);
    });
  } else {
    imageToken++;
    image.hidden = true;
    image.removeAttribute("src");
    baseImgW = 0;
    baseImgH = 0;
    empty.hidden = false;
    const heading = empty.querySelector("h1");
    const text = empty.querySelector("p");
    if (!state.total) {
      heading.textContent = "Nothing loaded";
      text.textContent = "Choose an image folder to start sorting.";
    } else if (state.skipped) {
      heading.textContent = "Only skipped images left";
      text.textContent = `${state.skipped} image(s) are waiting in the Skipped group below.`;
    } else {
      heading.textContent = "All done";
      text.textContent = `Sorted ${state.sorted} image(s).`;
    }
    $("info-name").textContent = "—";
    $("info-dims").textContent = "";
    $("info-size").textContent = "";
    $("info-sidecars").replaceChildren();
  }

  $("info-progress").textContent = state.total ? `${state.position || state.total} / ${state.total}` : "";
  const counts = $("info-counts");
  counts.replaceChildren();
  if (state.total) {
    const add = (label, value) => {
      const span = el("span");
      span.append(document.createTextNode(`${label} `));
      const bold = el("b");
      bold.textContent = value;
      span.append(bold);
      counts.append(span);
    };
    add("left", state.pending);
    add(state.config.apply_mode === "deferred" ? "decided" : "sorted", state.sorted);
    if (state.skipped) add("skipped", state.skipped);
    if (state.staged) add("waiting", state.staged);
  }
  const processed = state.total ? state.total - state.pending : 0;
  $("progress-fill").style.width = state.total ? `${(processed / state.total) * 100}%` : "0";

  const zoomToolbar = $("zoom-toolbar");
  if (zoomToolbar) zoomToolbar.hidden = !state.current || state.config.image_fit === "actual";
}

function renderFilmstrip() {
  const strip = $("filmstrip");
  strip.replaceChildren();
  state.upcoming.forEach((item) => {
    const box = el("div", "thumb");
    box.classList.toggle("active", item.index === state.target);
    box.classList.toggle("cursor-at", item.index === state.index);
    box.classList.toggle("selected",
      state.selection !== null && item.index === state.selection);
    const img = el("img");
    img.loading = "lazy";
    img.src = `/api/thumb/${item.index}?size=260&v=${state.revision}-${state.index}`;
    img.alt = item.name;
    img.draggable = false;
    const label = el("div", "label");
    label.textContent = item.name;
    box.append(img, label);
    box.title = `${item.name}\nPreview image or drag to a category`;

    // Clicking only changes what you are looking at; it decides nothing.
    box.addEventListener("click", async () => {
      if (draggingImage !== null) return;     // that was a drag, not a click
      render(await post(`/api/select/${item.index}`));
    });
    makeImageDraggable(box, item.index);
    strip.append(box);
  });
}

/**
 * Pick how many cards go on a row. A row that is not full stretches to the
 * width anyway (the cards are flex items), so nothing is ever left blank; this
 * just picks the arrangement that wastes the fewest slots at a sane shape.
 */
function cardGrid(count, width, height, gap) {
  const layout = state.config.card_layout;
  if (layout === "rows") return { columns: 1, rows: count };
  if (layout === "columns") return { columns: count, rows: 1 };

  const minWidth = 150, minHeight = 78, target = 2.2;
  let best = null;
  for (let columns = 1; columns <= count; columns++) {
    const rows = Math.ceil(count / columns);
    const w = (width - gap * (columns - 1)) / columns;
    const h = (height - gap * (rows - 1)) / rows;
    if (w < minWidth && columns > 1) continue;
    let score = Math.abs(Math.log((w / Math.max(h, 1)) / target));
    score += (columns * rows - count) * 0.35;      // prefer a full last row
    if (h < minHeight) score += 8 + (minHeight - h) / minHeight;
    if (!best || score < best.score) best = { columns, rows, score };
  }
  if (!best) best = { columns: 1, rows: count };
  return { columns: best.columns, rows: best.rows };
}

let draggingImage = null;      // the image index currently being dragged
let pointerDrag = null;        // the in-progress gesture, before it counts as a drag

const DRAG_THRESHOLD = 6;
const SKIPPED_ID = "skipped";

/**
 * Dragging an image onto a category card.
 *
 * This is done with pointer events rather than HTML5 drag and drop: the native
 * one is unreliable inside the desktop shell, and a cancelled drag could leave
 * the image stuck half transparent. Here the cleanup is unconditional.
 */
function makeImageDraggable(element, index) {
  element.draggable = false;
  element.addEventListener("dragstart", (event) => event.preventDefault());
  element.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    pointerDrag = {
      element,
      index: () => Number(element.dataset.index ?? index),
      startX: event.clientX,
      startY: event.clientY,
      active: false,
    };
  });
}

function cardUnder(x, y) {
  const node = document.elementFromPoint(x, y);
  const card = node && node.closest ? node.closest(".card[data-id]") : null;
  return card;
}

function beginImageDrag(event) {
  pointerDrag.active = true;
  draggingImage = pointerDrag.index();
  pointerDrag.element.classList.add("dragging");
  document.body.classList.add("dragging-image");

  const ghost = el("img", "drag-ghost");
  ghost.src = `/api/thumb/${draggingImage}?size=200`;
  ghost.style.width = "92px";
  ghost.style.height = "92px";
  document.body.append(ghost);
  pointerDrag.ghost = ghost;
  moveGhost(event);
}

function moveGhost(event) {
  const ghost = pointerDrag && pointerDrag.ghost;
  if (!ghost) return;
  ghost.style.left = `${event.clientX + 14}px`;
  ghost.style.top = `${event.clientY + 14}px`;
}

/** Always safe to call: leaves nothing behind, whatever went wrong. */
function endImageDrag() {
  if (pointerDrag && pointerDrag.ghost) pointerDrag.ghost.remove();
  pointerDrag = null;
  draggingImage = null;
  document.body.classList.remove("dragging-image");
  document.querySelectorAll(".dragging").forEach((n) => n.classList.remove("dragging"));
  document.querySelectorAll(".card.drop-target")
    .forEach((c) => c.classList.remove("drop-target"));
}

document.addEventListener("pointermove", (event) => {
  if (!pointerDrag) return;
  if (!pointerDrag.active) {
    const moved = Math.hypot(event.clientX - pointerDrag.startX,
                             event.clientY - pointerDrag.startY);
    if (moved < DRAG_THRESHOLD) return;
    beginImageDrag(event);
  }
  moveGhost(event);
  const over = cardUnder(event.clientX, event.clientY);
  document.querySelectorAll(".card.drop-target").forEach((c) => {
    if (c !== over) c.classList.remove("drop-target");
  });
  if (over) over.classList.add("drop-target");
});

document.addEventListener("pointerup", async (event) => {
  if (!pointerDrag) return;
  const wasDragging = pointerDrag.active;
  const index = pointerDrag.index();
  const card = wasDragging ? cardUnder(event.clientX, event.clientY) : null;
  endImageDrag();
  if (!wasDragging || !card) return;
  const categoryId = card.dataset.id;
  flashCard(categoryId);
  render(categoryId === SKIPPED_ID
    ? await post(`/api/skip?index=${index}`)
    : await post(`/api/sort/${categoryId}?index=${index}`));
});

document.addEventListener("pointercancel", endImageDrag);
window.addEventListener("blur", endImageDrag);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && pointerDrag) endImageDrag();
});

function renderCards() {
  const wrap = $("categories");
  wrap.replaceChildren();
  const ready = state.setup.ready;
  $("bottom").hidden = false;
  $("resize-dock").hidden = !ready;
  $("layout").classList.toggle("setup-required", !ready);
  if (!ready) {
    wrap.style.removeProperty("--card-basis");
    wrap.style.alignContent = "stretch";
    const missingRoot = !state.config.output_root && state.categories.some((c) => c.relative);
    const hint = el("div", "dock-empty");
    const text = el("span");
    text.textContent = missingRoot
      ? "Choose an output folder before sorting."
      : state.setup.error;
    const button = el("button", "btn primary small");
    button.textContent = missingRoot ? "Choose output folder" : "Set up categories";
    button.title = missingRoot ? "Choose where sorted images will go" : "Configure category folders";
    button.addEventListener("click", () => {
      if (missingRoot) {
        chooseFolder({
          title: "Output folder",
          start: env.home,
          onPick: (picked) => saveSetting({ output_root: picked }),
        });
      } else {
        openCategoryTable();
      }
    });
    hint.append(text, button);
    wrap.append(hint);
    updateControls();
    return;
  }

  const cards = state.categories.map(buildCategoryCard);
  if (state.skipped > 0) cards.push(buildSkippedCard());

  if (!cards.length) {
    wrap.style.removeProperty("--card-basis");
    const hint = el("div", "dock-empty");
    const text = el("span");
    text.textContent = "No categories yet.";
    const button = el("button", "btn primary small");
    button.textContent = "Set up categories";
    button.addEventListener("click", () => openCategoryTable());
    hint.append(text, button);
    wrap.append(hint);
    updateControls();
    return;
  }

  const gap = 10;
  const width = wrap.clientWidth || 800;
  const height = wrap.clientHeight || 120;
  const { columns, rows } = cardGrid(cards.length, width, height, gap);

  // A basis just under the exact share makes the browser break the line where
  // we want it; `flex-grow` then takes the rounding and the short last row.
  const basis = Math.max(60, Math.floor((width - gap * (columns - 1)) / columns) - 1);
  wrap.style.setProperty("--card-basis", `${basis}px`);
  wrap.style.alignContent = rows * 78 > height ? "flex-start" : "stretch";
  cards.forEach((card) => wrap.append(card));

  // On a narrow card the name matters more than the count and the pencil.
  const cardWidth = (width - gap * (columns - 1)) / columns;
  wrap.classList.toggle("compact", cardWidth < 210);
  wrap.classList.toggle("very-compact", cardWidth < 165);

  updateControls();
  fillPreviews();
}

function buildCategoryCard(category) {
  const card = el("button", "card");
  card.style.setProperty("--cat-color", category.color);
  card.dataset.id = category.id;
  card.dataset.version = `${state.revision}-${category.in_folder}-${category.staged_here}`;
  card.classList.toggle("has-waiting", category.staged_here > 0);

  const waiting = category.staged_here;
  const verb = state.config.file_action === "copy" ? "copied" : "moved";
  card.title = category.problem
    || `${category.name} \u2192 ${category.resolved}\n`
       + `${category.in_folder} image(s) in the folder`
       + (waiting ? `, ${waiting} waiting to be ${verb} there` : "")
       + (category.hotkey ? `\nHotkey: ${category.hotkey}` : "");

  // -- header: name, count, edit, hotkey
  const head = el("div", "card-head");
  const name = el("span", "card-name");
  name.textContent = category.name;
  head.append(name);

  if (state.config.show_card_counts && !category.problem) {
    const count = el("span", "card-count");
    count.textContent = waiting ? `${category.count} (${waiting} waiting)` : `${category.count}`;
    count.title = waiting
      ? `${category.in_folder} already in the folder, ${waiting} waiting to be ${verb} there`
      : `${category.in_folder} image(s) in this folder`;
    head.append(count);
  }

  const edit = el("span", "edit");
  edit.textContent = "\u270e";
  edit.title = `Edit "${category.name}"`;
  edit.addEventListener("click", (event) => {
    event.stopPropagation();
    openCategoryTable(category.id);
  });
  head.append(edit);

  const hk = el("span", "hk" + (category.hotkey ? "" : " none"));
  hk.textContent = category.hotkey || "\u2013";
  hk.title = category.hotkey ? `Sort into ${category.name} (${category.hotkey})` : "No shortcut assigned";
  head.append(hk);
  card.append(head);

  // -- body: the images that belong here
  if (category.problem) {
    const problem = el("div", "card-empty card-problem");
    problem.textContent = "Needs an output root";
    card.append(problem);
  } else if (state.config.show_card_thumbnails) {
    card.append(el("div", "card-previews"));
  } else {
    const spacer = el("div", "card-empty");
    spacer.textContent = `${category.count} image(s)`;
    card.append(spacer);
  }

  card.addEventListener("click", (event) => {
    if (event.detail === 0) return;           // not a real click
    sortInto(category.id);
  });
  card.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    openCardMenu(event, category);
  });
  return card;
}

function buildSkippedCard() {
  const card = el("button", "card skipped");
  card.dataset.id = SKIPPED_ID;
  card.dataset.version = `${state.revision}-${state.skipped}`;
  card.title = "Review skipped images. Drag an image here to skip it.";

  const head = el("div", "card-head");
  const name = el("span", "card-name");
  name.textContent = "Skipped";
  const count = el("span", "card-count");
  count.textContent = state.skipped;
  head.append(name, count);
  card.append(head);

  if (state.config.show_card_thumbnails) {
    card.append(el("div", "card-previews"));
  } else {
    const body = el("div", "card-empty");
    body.textContent = "click to revisit";
    card.append(body);
  }

  card.addEventListener("click", async (event) => {
    if (event.detail === 0) return;
    render(await post("/api/skipped/review"));
  });
  card.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    const menu = $("context-menu");
    menu.replaceChildren();
    openMenu = "card";
    const head = el("div", "head");
    head.textContent = `Skipped (${state.skipped})`;
    menu.append(head);
    menuItem(menu, "Put them all back",
             "Return all skipped images to the queue",
             async () => render(await post("/api/skipped/review")));
    menuItem(menu, "Put the last one back",
             "Return the most recently skipped image",
             async () => {
               const data = await api(`/api/categories/${SKIPPED_ID}/previews?limit=1`);
               const first = data && data.previews && data.previews[0];
               if (first && first.index >= 0) {
                 render(await post(`/api/skipped/restore/${first.index}`));
               }
             });
    placeMenu(menu, event.clientX, event.clientY);
  });
  return card;
}

/** Fill each card with as many image previews as its box can hold. */
const previewCache = new Map();

async function fillPreviews() {
  if (!state.config.show_card_thumbnails) return;
  const tile = state.config.card_thumb_size;

  for (const card of document.querySelectorAll(".card[data-id]")) {
    const box = card.querySelector(".card-previews");
    if (!box) continue;
    const width = box.clientWidth, height = box.clientHeight;
    // Tiles keep the chosen shape; the size setting is their long edge.
    const ratio = aspect();
    const tileWidth = ratio >= 1 ? tile : Math.round(tile * ratio);
    const tileHeight = ratio >= 1 ? Math.round(tile / ratio) : tile;
    const columns = Math.max(1, Math.floor((width + 3) / (tileWidth + 3)));
    const rows = Math.max(1, Math.floor((height + 3) / (tileHeight + 3)));
    const capacity = Math.min(columns * rows, 24);
    // Fixed tracks, not 1fr: the tiles must keep the chosen shape exactly.
    box.style.gridTemplateColumns = `repeat(${columns}, ${tileWidth}px)`;
    box.style.gridAutoRows = `${tileHeight}px`;
    box.style.justifyContent = "start";

    const id = card.dataset.id;
    const key = `${id}:${card.dataset.version}:${capacity}`;
    let previews = previewCache.get(key);
    if (!previews) {
      const data = await api(`/api/categories/${id}/previews?limit=${capacity}`);
      previews = (data && data.previews) || [];
      previewCache.set(key, previews);
      if (previewCache.size > 200) previewCache.clear();
    }
    if (!card.isConnected) continue;

    const isSkipped = id === SKIPPED_ID;
    box.replaceChildren();
    previews.forEach((preview) => {
      const image = el("img");
      image.loading = "lazy";
      image.alt = preview.name;
      image.title = isSkipped
        ? `${preview.name}: return to the queue`
        : (preview.waiting ? `${preview.name}: pending` : preview.name);
      image.src = `/api/categories/${id}/preview/${preview.n}`
                + `?size=${Math.max(64, tile * 2)}&v=${card.dataset.version}`;
      if (preview.waiting) image.classList.add("waiting");
      if (isSkipped && preview.index >= 0) {
        image.classList.add("restorable");
        image.addEventListener("click", async (event) => {
          event.stopPropagation();
          render(await post(`/api/skipped/restore/${preview.index}`));
        });
      }
      box.append(image);
    });
    if (!previews.length) {
      const empty = el("div", "previews-empty");
      empty.textContent = "empty";
      box.append(empty);
    }
  }
}

function updateControls() {
  const waiting = state.staged;
  const copying = state.config.file_action === "copy";
  const verb = copying ? "Copy" : "Move";

  $("btn-undo").disabled = !state.can_undo;
  $("btn-skip").disabled = !state.current || !state.setup.ready;
  $("btn-skip").title =
    "Skip this image for now"
    + (state.config.skip_hotkey ? ` (${state.config.skip_hotkey})` : "");
  $("btn-apply").hidden = !waiting;
  $("btn-apply").disabled = !state.setup.ready;
  $("btn-discard").hidden = !waiting;

  // The buttons stay short; the count and the consequence live in the tooltip.
  const files = `${waiting} image${waiting === 1 ? "" : "s"}`;
  const one = waiting === 1;
  $("btn-apply").title = waiting
    ? `${verb} ${files} to their assigned categories (Ctrl+Enter)`
    : "";
  $("btn-discard").title = waiting
    ? `Cancel ${waiting} pending assignment${one ? "" : "s"} and return the images to the queue`
    : "";

}

let lastStatus = "";
let lastWarnings = "";
function renderStatus() {
  const status = state.status || "";
  const warnings = (state.warnings || []).join(" ");
  const messages = [];
  const notifyStatus = status.startsWith("Carried on from last time")
    || status === "No images found in that folder."
    || status === "Those images are already in the list.";
  if (notifyStatus && status !== lastStatus) messages.push(status);
  if (warnings && warnings !== lastWarnings) messages.push(warnings);
  lastStatus = status;
  lastWarnings = warnings;
  if (messages.length && !state.error) toast(messages.join(" "));
  const label = state.project.source_label;
  $("folder-label").textContent = label || "Image folder…";
  $("btn-folder").classList.toggle("dropped", state.project.dropped);
  $("btn-folder").title = label
    ? `${label}\nChoose another image folder (Ctrl+O)`
    : "Choose an image folder (Ctrl+O)";
}

function shorten(path, max) {
  if (!path) return "";
  return path.length <= max ? path : "…" + path.slice(-(max - 1));
}

/* --------------------------------------------------------------- actions */
async function sortInto(categoryId) {
  if (!state.setup.ready) {
    openCategoryTable();
    return;
  }
  flashCard(categoryId);
  render(await post(`/api/sort/${categoryId}`));
}

function flashCard(categoryId) {
  const card = document.querySelector(`.card[data-id="${categoryId}"]`);
  if (!card) return;
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 190);
}

const refresh = async () => render(await api("/api/state"));

/* ----------------------------------------------------------- context menu */
let openMenu = null;          // which menu the popup is currently showing

function closeCardMenu() {
  $("context-menu").hidden = true;
  openMenu = null;
}
document.addEventListener("click", closeCardMenu);
document.addEventListener("scroll", closeCardMenu, true);
window.addEventListener("blur", closeCardMenu);

function menuItem(menu, label, title, handler, options = {}) {
  const button = el("button", options.danger ? "danger" : "");
  button.textContent = label;
  button.title = title;
  button.disabled = !!options.disabled;
  button.addEventListener("click", (e) => { e.stopPropagation(); closeCardMenu(); handler(); });
  menu.append(button);
  return button;
}

function placeMenu(menu, x, y) {
  menu.hidden = false;
  const box = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - box.width - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - box.height - 8))}px`;
}

function openAppMenu() {
  if (openMenu === "app") { closeCardMenu(); return; }   // second click closes it
  const menu = $("context-menu");
  menu.replaceChildren();
  openMenu = "app";

  menuItem(menu, "Settings…", "Folders, sorting, view and startup options", openSettings);
  menuItem(menu, "Keyboard shortcuts", "View keyboard shortcuts",
           () => openModal("modal-help"));
  menu.append(el("div", "sep"));
  menuItem(menu, state.project.path ? "Save project" : "Save project as…",
           "Save the current project (Ctrl+S)", saveProject);
  menuItem(menu, "Load project…", "Open a saved project",
           loadProject);
  menu.append(el("div", "sep"));
  menuItem(menu, "Clear input", state.total
             ? "Unload images and cancel pending assignments. Keep categories and settings."
             : "No images loaded",
           clearInput, { disabled: !state.total });
  menuItem(menu, "Clear output", "Return sorted images and cancel pending placements",
           clearOutput, { disabled: !state.categories.some(category => category.clearable) });

  const button = $("btn-menu").getBoundingClientRect();
  menu.hidden = false;
  const box = menu.getBoundingClientRect();
  placeMenu(menu, button.right - box.width, button.bottom + 6);
}

function openCardMenu(event, category) {
  const menu = $("context-menu");
  menu.replaceChildren();
  openMenu = "card";

  const head = el("div", "head");
  head.textContent = category.name;
  menu.append(head);

  const item = (label, title, handler, options = {}) =>
    menuItem(menu, label, title, handler, options);

  item("Edit…", `Edit ${category.name}`,
       () => openCategoryTable(category.id));
  item("Create its folder", "Create missing category folders",
       async () => {
         render(await post("/api/categories/create-folders"));
         toast("Folders created.");
       }, { disabled: !!category.problem });

  menu.append(el("div", "sep"));

  const clearable = category.clearable;
  item(`Clear${clearable ? ` (${clearable})` : ""}`,
       clearable
         ? "Return this category's images to their original folders for sorting again"
         : "This category is empty",
       () => clearCategory(category),
       { danger: true, disabled: !clearable });

  placeMenu(menu, event.clientX, event.clientY);
}

async function clearInput() {
  const bits = [`${state.total} image(s) are loaded`];
  if (state.sorted) {
    bits.push(state.staged
      ? `${state.sorted} decided, ${state.staged} of them still waiting to be applied`
      : `${state.sorted} already sorted`);
  }
  if (state.skipped) bits.push(`${state.skipped} skipped`);
  const warning = state.staged
    ? "\n\nThe waiting decisions are thrown away — nothing is written to disk.\n"
      + "Files already moved stay where they are."
    : "\n\nFiles already moved stay where they are.";
  if (!await askConfirmation(`Clear the input?\n\n${bits.join("\n")}.${warning}\n\n`
             + "Your categories, hotkeys and settings are kept.")) return;
  render(await post("/api/input/clear"));
  toast("Input cleared.");
}

async function clearOutput() {
  const pending = state.categories.reduce((total, category) => total + category.staged_here, 0);
  const onDisk = state.categories.some(category => category.clearable_on_disk);
  const parts = [];
  if (pending) parts.push(`Cancel ${pending} pending placement(s).`);
  if (onDisk) parts.push("Return moved images to their original folders and remove output copies. Other images in category folders return to the source folder when available. These file changes happen immediately.");
  if (!await askConfirmation(`Clear all output?\n\n${parts.join("\n")}\n\nImages return to the sorting queue.`)) return;
  render(await post("/api/output/clear"));
}

async function clearCategory(category) {
  const onDisk = category.clearable_on_disk;
  const waiting = category.staged_here;
  const parts = [];
  if (waiting) parts.push(`Cancel ${waiting} pending decision(s). These files have not been moved or copied.`);
  if (onDisk) parts.push(`${onDisk} image(s) already exist in the category folder. Clearing undoes applied moves or copies and returns other files to the source folder. This happens immediately, including when Apply is manual.`);
  if (!await askConfirmation(`Clear "${category.name}"?\n\n${parts.join("\n")}\n\n`
             + "Those images go back into the queue so you can decide again.")) return;
  render(await post(`/api/categories/${category.id}/clear`));
}

/* ---------------------------------------------------------------- modals */
let activeModal = null;
const modalStack = [];
let finishConfirmation = null;

function openModal(id) {
  if (id === "modal-help") {
    const slot = $("help-skip-hotkey");
    slot.replaceChildren();
    if (state.config?.skip_hotkey) {
      const key = el("kbd");
      key.textContent = state.config.skip_hotkey;
      slot.append(key);
    } else {
      slot.textContent = "–";
    }
  }
  if (activeModal) $(activeModal).hidden = true;
  activeModal = id;
  $("modal-backdrop").hidden = false;
  $(id).hidden = false;
}

function closeModal() {
  if (activeModal === "modal-confirm") {
    finishConfirmation(false);
    return;
  }
  if (activeModal) $(activeModal).hidden = true;
  activeModal = null;
  $("modal-backdrop").hidden = true;
  stopHotkeyCapture();
  const resume = modalStack.pop();
  if (resume) resume();
}

document.querySelectorAll("[data-close]").forEach((node) =>
  node.addEventListener("click", closeModal));

$("modal-backdrop").addEventListener("mousedown", (event) => {
  if (event.target === $("modal-backdrop")) closeModal();
});

function askConfirmation(message) {
  return new Promise((resolve) => {
    const previousModal = activeModal;
    const previousFocus = document.activeElement;
    const [title, ...body] = message.split("\n\n");
    $("confirm-title").textContent = title;
    $("confirm-message").textContent = body.join("\n\n");
    finishConfirmation = (accepted) => {
      finishConfirmation = null;
      $("modal-confirm").hidden = true;
      activeModal = null;
      if (previousModal) openModal(previousModal);
      else $("modal-backdrop").hidden = true;
      if (previousFocus?.isConnected) previousFocus.focus();
      resolve(accepted);
    };
    openModal("modal-confirm");
    $("confirm-cancel").focus();
  });
}

$("confirm-ok").addEventListener("click", () => finishConfirmation?.(true));
$("modal-confirm").addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    const next = document.activeElement === $("confirm-cancel") ? "confirm-ok" : "confirm-cancel";
    $(next).focus();
  }
});

/** A themed replacement for window.prompt (which native shells may block). */
function askText(title, value) {
  return new Promise((resolve) => {
    const previous = activeModal;
    $("prompt-title").textContent = title;
    $("prompt-input").value = value || "";
    openModal("modal-prompt");
    $("prompt-input").focus();
    $("prompt-input").select();

    const finish = (result) => {
      $("prompt-ok").removeEventListener("click", onOk);
      $("prompt-input").removeEventListener("keydown", onKey);
      $("modal-prompt").hidden = true;
      activeModal = null;
      if (previous) { openModal(previous); } else { $("modal-backdrop").hidden = true; }
      resolve(result);
    };
    const onOk = () => finish($("prompt-input").value.trim() || null);
    const onKey = (event) => {
      if (event.key === "Enter") { event.preventDefault(); onOk(); }
      if (event.key === "Escape") { event.preventDefault(); finish(null); }
    };
    $("prompt-ok").addEventListener("click", onOk);
    $("prompt-input").addEventListener("keydown", onKey);
  });
}

/* ------------------------------------------------------- folder browsing */
let browseState = { path: "", mode: "folder", onPick: null, selectedFile: "" };

async function openBrowser({ title, start, mode, confirmLabel, onPick, resume }) {
  browseState = { path: start || env.home, mode: mode || "folder", onPick, selectedFile: "" };
  $("browse-title").textContent = title;
  $("browse-confirm").textContent = confirmLabel || "Select";
  $("browse-newfolder").hidden = mode === "file";
  if (resume) modalStack.push(resume);
  openModal("modal-browse");
  await loadBrowser(browseState.path);
}

async function loadBrowser(path) {
  const endpoint = browseState.mode === "file"
    ? `/api/browse/files?path=${encodeURIComponent(path || "")}`
    : `/api/browse?path=${encodeURIComponent(path || "")}`;
  const data = await api(endpoint);
  if (!data) return;

  browseState.path = data.path;
  browseState.selectedFile = "";
  $("browse-path").value = data.path;

  const drives = $("browse-drives");
  drives.replaceChildren();
  (data.drives || []).forEach((drive) => {
    const b = el("button");
    b.textContent = drive;
    b.addEventListener("click", () => loadBrowser(drive));
    drives.append(b);
  });

  const list = $("browse-list");
  list.replaceChildren();
  const select = (li, path, isFile) => {
    list.querySelectorAll("li").forEach((n) => n.classList.remove("selected"));
    li.classList.add("selected");
    if (isFile) {
      browseState.selectedFile = path;
    } else {
      browseState.selectedFile = "";
      browseState.path = path;
      $("browse-path").value = path;
    }
  };

  data.folders.forEach((folder) => {
    const li = el("li");
    li.textContent = "📁 " + folder.name;
    li.addEventListener("click", () => select(li, folder.path, false));
    li.addEventListener("dblclick", () => loadBrowser(folder.path));
    list.append(li);
  });
  (data.files || []).forEach((file) => {
    const li = el("li", "file");
    li.textContent = "📄 " + file.name;
    li.addEventListener("click", () => select(li, file.path, true));
    li.addEventListener("dblclick", () => { browseState.selectedFile = file.path; $("browse-confirm").click(); });
    list.append(li);
  });

  $("browse-note").textContent = data.error
    || (browseState.mode === "folder" ? `${data.images} image(s) directly in this folder.` : "");
}

$("browse-up").addEventListener("click", async () => {
  const data = await api(`/api/browse?path=${encodeURIComponent(browseState.path)}`);
  if (data && data.parent) loadBrowser(data.parent);
});
$("browse-go").addEventListener("click", () => loadBrowser($("browse-path").value));
$("browse-path").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadBrowser($("browse-path").value);
});
$("browse-newfolder").addEventListener("click", async () => {
  const name = await askText("Name of the new folder");
  if (!name) return;
  const data = await post("/api/browse/new", { parent: browseState.path, name });
  if (data && !data.error) loadBrowser(data.path);
});
$("browse-confirm").addEventListener("click", () => {
  const value = browseState.mode === "file"
    ? browseState.selectedFile
    : ($("browse-path").value || browseState.path);
  if (!value) { toast("Nothing selected.", true); return; }
  const callback = browseState.onPick;
  // The pick callback re-opens the caller itself, so drop its cancel-resume
  // instead of letting closeModal() run it.
  modalStack.pop();
  if (activeModal) $(activeModal).hidden = true;
  activeModal = null;
  $("modal-backdrop").hidden = true;
  stopHotkeyCapture();
  if (callback) callback(value);
});

/* ------------------------------------------------- the category table */
let tableRows = [];
let dragRowId = null;

function blankRow() {
  return { id: "", name: "", folder: "", hotkey: "", color: pickColor(tableRows.length), count: 0 };
}

function pickColor(index) {
  const palette = ["#4f8ef7", "#f7794f", "#3fb98a", "#c264e0",
                   "#e4b23c", "#3fb6c9", "#e0648f", "#8a7ef0"];
  return palette[index % palette.length];
}

function openCategoryTable(focusId) {
  tableRows = state.categories.map((c) => ({
    id: c.id, name: c.name, folder: c.folder, hotkey: c.hotkey,
    color: c.color, count: c.count,
  }));
  if (!tableRows.length) tableRows.push(blankRow());
  $("table-root").value = state.config.output_root || "";
  renderPresetOptions();
  renderTableRows(focusId);
  $("bulk-names").value = "";
  openModal("modal-categories");
}

function renderPresetOptions() {
  const select = $("preset-select");
  const chosen = select.value;
  select.replaceChildren();
  const none = el("option");
  none.value = "";
  none.textContent = state.presets.length ? "— pick a preset —" : "— no presets saved —";
  select.append(none);
  state.presets.forEach((name) => {
    const option = el("option");
    option.value = name;
    option.textContent = name;
    select.append(option);
  });
  if (state.presets.includes(chosen)) select.value = chosen;
}

function renderTableRows(focusId) {
  const body = $("cat-rows");
  body.replaceChildren();

  tableRows.forEach((row, index) => {
    const tr = el("tr");
    tr.dataset.index = String(index);

    const drag = el("td", "drag");
    drag.textContent = "⠿";
    drag.title = "Drag to reorder";
    drag.draggable = true;
    drag.addEventListener("dragstart", () => { dragRowId = index; tr.classList.add("dragging"); });
    drag.addEventListener("dragend", () => { dragRowId = null; tr.classList.remove("dragging"); });
    tr.append(drag);

    tr.addEventListener("dragover", (event) => { event.preventDefault(); tr.classList.add("drop-target"); });
    tr.addEventListener("dragleave", () => tr.classList.remove("drop-target"));
    tr.addEventListener("drop", (event) => {
      event.preventDefault();
      tr.classList.remove("drop-target");
      if (dragRowId === null || dragRowId === index) return;
      const [moved] = tableRows.splice(dragRowId, 1);
      tableRows.splice(index, 0, moved);
      dragRowId = null;
      renderTableRows();
    });

    const colorCell = el("td");
    const color = el("input");
    color.type = "color";
    color.value = row.color || pickColor(index);
    color.addEventListener("input", () => { row.color = color.value; });
    colorCell.append(color);
    tr.append(colorCell);

    const nameCell = el("td");
    const name = el("input");
    name.type = "text";
    name.value = row.name;
    name.placeholder = "Keep";
    name.addEventListener("input", () => { row.name = name.value; });
    nameCell.append(name);
    tr.append(nameCell);

    const folderCell = el("td");
    const wrap = el("div", "folder-cell");
    const folder = el("input");
    folder.type = "text";
    folder.value = row.folder;
    folder.addEventListener("input", () => { row.folder = folder.value; });
    const useName = el("button", "mini");
    useName.type = "button";
    useName.textContent = "= name";
    useName.title = "Use the category name as the folder name";
    useName.addEventListener("click", () => { row.folder = row.name; folder.value = row.name; });
    const browse = el("button", "mini");
    browse.type = "button";
    browse.textContent = "…";
    browse.title = "Browse for a folder";
    browse.addEventListener("click", () => {
      const root = $("table-root").value;
      openBrowser({
        title: `Folder for "${row.name || "category"}"`,
        start: row.folder || root || env.home,
        mode: "folder",
        // `tableRows` is the table's only source of truth and nothing else
        // touches it, so there is nothing to save and restore here.
        resume: () => openModal("modal-categories"),
        onPick: (picked) => {
          row.folder = relativiseIfPossible(picked, root);
          openModal("modal-categories");
          renderTableRows();
        },
      });
    });
    wrap.append(folder, useName, browse);
    folderCell.append(wrap);
    tr.append(folderCell);

    const hotkeyCell = el("td");
    const hotkey = el("input", "hotkey-input");
    hotkey.type = "text";
    hotkey.readOnly = true;
    hotkey.value = row.hotkey;
    hotkey.placeholder = "click, press a key";
    hotkey.addEventListener("focus", () => startHotkeyCapture(hotkey, row));
    hotkey.addEventListener("blur", stopHotkeyCapture);
    hotkeyCell.append(hotkey);
    tr.append(hotkeyCell);

    const countCell = el("td", "col-count");
    countCell.textContent = row.id ? row.count : "—";
    tr.append(countCell);

    const delCell = el("td");
    const del = el("button", "row-del");
    del.type = "button";
    del.textContent = "✕";
    del.title = "Remove category";
    del.addEventListener("click", () => {
      tableRows.splice(index, 1);
      if (!tableRows.length) tableRows.push(blankRow());
      renderTableRows();
    });
    delCell.append(del);
    tr.append(delCell);

    body.append(tr);

    if (focusId && row.id === focusId) setTimeout(() => name.focus(), 0);
  });
}

/** Turn an absolute path under the output root into a plain folder name. */
function relativiseIfPossible(picked, root) {
  if (!root) return picked;
  const normal = (p) => p.replace(/[\\/]+$/, "").toLowerCase();
  const rootNorm = normal(root);
  if (normal(picked).startsWith(rootNorm + "\\") || normal(picked).startsWith(rootNorm + "/")) {
    return picked.slice(root.replace(/[\\/]+$/, "").length + 1);
  }
  return picked;
}

let capturingInput = null;
function startHotkeyCapture(input, row, onCommit) {
  capturingInput = { input, row, onCommit };
  input.classList.add("capturing");
  input.dataset.previous = input.value;
  input.value = "press a key…";
}

function stopHotkeyCapture() {
  if (!capturingInput) return;
  const { input } = capturingInput;
  input.classList.remove("capturing");
  if (input.value === "press a key…") input.value = input.dataset.previous || "";
  capturingInput = null;
}

$("cat-add-row").addEventListener("click", () => {
  tableRows.push(blankRow());
  renderTableRows();
  const inputs = $("cat-rows").querySelectorAll("tr:last-child input[type=text]");
  if (inputs.length) inputs[0].focus();
});

$("table-root").addEventListener("change", async () => {
  const result = await post("/api/settings", { output_root: $("table-root").value.trim() });
  if (result) render(result);
  renderTableRows();
});

$("table-root-browse").addEventListener("click", () => {
  openBrowser({
    title: "Output folder",
    start: $("table-root").value || env.home,
    mode: "folder",
    confirmLabel: "Use this folder",
    resume: () => openModal("modal-categories"),
    onPick: async (picked) => {
      openModal("modal-categories");
      $("table-root").value = picked;
      const result = await post("/api/settings", { output_root: picked });
      if (result) render(result);
      renderTableRows();
    },
  });
});

$("bulk-add").addEventListener("click", async () => {
  const names = $("bulk-names").value.split("\n").map((n) => n.trim()).filter(Boolean);
  if (!names.length) { toast("Type one category name per line first.", true); return; }
  // Persist what is on screen, then append the new ones.
  const saved = await put("/api/categories", { categories: tableRows });
  if (!saved || saved.error) return;
  const result = await post("/api/categories/bulk", { names });
  if (!result || result.error) return;
  render(result);
  $("bulk-names").value = "";
  openCategoryTable();
  toast(`Added ${names.length} categor${names.length === 1 ? "y" : "ies"}.`);
});

$("cat-make-folders").addEventListener("click", async () => {
  const saved = await put("/api/categories", { categories: tableRows });
  if (!saved || saved.error) return;
  render(await post("/api/categories/create-folders"));
  openCategoryTable();
});

$("cat-table-save").addEventListener("click", async () => {
  const named = tableRows.filter((row) => row.name.trim());
  const missing = named.filter((row) => !row.folder.trim());
  if (missing.length) {
    toast(`"${missing[0].name}" has no folder. Use "= name" or pick one.`, true);
    return;
  }
  const result = await put("/api/categories", { categories: named });
  if (!result || result.error) return;
  render(result);
  if (!state.setup.ready) {
    toast(state.setup.error, true);
    return;
  }
  closeModal();
});

/* ------------------------------------------------------------- presets */
$("preset-save").addEventListener("click", async () => {
  const saved = await put("/api/categories", { categories: tableRows.filter((r) => r.name.trim()) });
  if (!saved || saved.error) return;
  const name = await askText("Save these categories as a preset called");
  if (!name) return;
  const result = await post("/api/presets/save", { name });
  if (!result || result.error) return;
  render(result);
  openCategoryTable();
  $("preset-select").value = name;
  toast(`Preset "${name}" saved.`);
});

async function applyPreset(replace) {
  const name = $("preset-select").value;
  if (!name) { toast("Pick a preset first.", true); return; }
  const result = await post("/api/presets/load", { name, replace });
  if (!result || result.error) return;
  render(result);
  openCategoryTable();
  $("preset-select").value = name;
}
$("preset-load").addEventListener("click", () => applyPreset(true));
$("preset-append").addEventListener("click", () => applyPreset(false));

$("preset-delete").addEventListener("click", async () => {
  const name = $("preset-select").value;
  if (!name) { toast("Pick a preset first.", true); return; }
  const result = await post("/api/presets/delete", { name });
  if (!result || result.error) return;
  render(result);
  openCategoryTable();
});

/* -------------------------------------------------------------- settings */
function fillSelect(select, values, current) {
  select.replaceChildren();
  const labels = {
    name: "File name", newest: "Newest first", oldest: "Oldest first",
    largest: "Largest first", smallest: "Smallest first", random: "Random",
    contain: "Fit inside the window", cover: "Fill the window (crops)", actual: "Actual size",
    vertical: "Vertical (9:16)", horizontal: "Horizontal (16:9)", square: "Square (1:1)",
    grid: "Fit them into a grid", rows: "One per row", columns: "All on one row",
    move: "Move them out of the source folder",
    copy: "Copy them, leaving the originals in place",
    immediate: "Straight away, as I press each key",
    deferred: "Only when I press Apply",
  };
  values.forEach((value) => {
    const option = el("option");
    option.value = value;
    option.textContent = labels[value] || value;
    select.append(option);
  });
  select.value = current;
}

function openSettings() {
  const config = state.config;
  $("set-output-root").value = config.output_root || "";
  $("set-recursive").checked = config.recursive;
  fillSelect($("set-sort-order"), env.sort_orders, config.sort_order);
  fillSelect($("set-file-action"), env.file_actions, config.file_action);
  fillSelect($("set-apply-mode"), env.apply_modes, config.apply_mode);
  $("apply-mode-hint").textContent = config.apply_mode === "deferred"
    ? "Decisions are collected as you go and nothing on disk changes until you press "
      + "the Apply button in the bar below. Cancel throws the waiting decisions away."
    : "Each file is handled the moment you pick a category. Ctrl+Z puts it back.";
  $("set-skip-hotkey").value = config.skip_hotkey || "";
  $("set-sidecars").checked = config.move_sidecars;
  $("set-sidecar-ext").value = (config.sidecar_extensions || []).join(", ");
  $("set-filmstrip").checked = config.show_filmstrip;
  $("set-full-strip").checked = config.full_height_strip;
  fillSelect($("set-thumb-ratio"), env.thumb_ratios, config.thumb_ratio);
  fillSelect($("set-card-layout"), env.card_layouts, config.card_layout);
  $("set-card-thumbs").checked = config.show_card_thumbnails;
  $("set-card-thumb-size").value = config.card_thumb_size;
  $("set-card-thumb-size-value").textContent = `${config.card_thumb_size}px`;
  $("set-card-counts").checked = config.show_card_counts;
  fillSelect($("set-image-fit"), env.image_fits, config.image_fit);
  $("set-autosave").checked = config.autosave;
  $("set-remember").checked = config.remember_last_project;
  $("set-config-path").textContent = env.config_file;
  openModal("modal-settings");
}

const saveSetting = async (changes) => render(await post("/api/settings", changes));

$("set-output-root").addEventListener("change", (e) => saveSetting({ output_root: e.target.value.trim() }));
$("set-root-browse").addEventListener("click", () => {
  if (env.native_dialogs) {
    chooseFolder({
      title: "Output folder",
      start: $("set-output-root").value || env.home,
      onPick: async (picked) => { await saveSetting({ output_root: picked }); openSettings(); },
    });
    return;
  }
  openBrowser({
    title: "Output folder",
    start: $("set-output-root").value || env.home,
    mode: "folder",
    confirmLabel: "Use this folder",
    resume: () => openSettings(),
    onPick: async (picked) => {
      await saveSetting({ output_root: picked });
      openSettings();
    },
  });
});
$("set-recursive").addEventListener("change", (e) => saveSetting({ recursive: e.target.checked }));
$("set-sort-order").addEventListener("change", (e) => saveSetting({ sort_order: e.target.value }));
$("set-file-action").addEventListener("change", async (e) => {
  await saveSetting({ file_action: e.target.value });
  openSettings();
});
$("set-apply-mode").addEventListener("change", async (e) => {
  await saveSetting({ apply_mode: e.target.value });
  openSettings();
});
$("set-skip-hotkey").addEventListener("focus", (e) =>
  startHotkeyCapture(e.target, null, async (value) => {
    await saveSetting({ skip_hotkey: value });
    // A key already taken by a category is refused; show what was kept.
    e.target.value = state.config.skip_hotkey || "";
  }));
$("set-skip-hotkey").addEventListener("blur", stopHotkeyCapture);
$("set-skip-hotkey-clear").addEventListener("click", async () => {
  $("set-skip-hotkey").value = "";
  await saveSetting({ skip_hotkey: "" });
});
$("set-sidecars").addEventListener("change", (e) => saveSetting({ move_sidecars: e.target.checked }));
$("set-sidecar-ext").addEventListener("change", (e) =>
  saveSetting({ sidecar_extensions: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) }));
$("set-filmstrip").addEventListener("change", (e) => saveSetting({ show_filmstrip: e.target.checked }));
$("set-full-strip").addEventListener("change", (e) => saveSetting({ full_height_strip: e.target.checked }));
$("set-thumb-ratio").addEventListener("change", async (e) => {
  previewCache.clear();
  await saveSetting({ thumb_ratio: e.target.value });
});
$("set-card-layout").addEventListener("change", (e) => saveSetting({ card_layout: e.target.value }));
$("set-card-thumb-size").addEventListener("input", (e) => {
  $("set-card-thumb-size-value").textContent = `${e.target.value}px`;
  document.documentElement.style.setProperty("--tile", `${e.target.value}px`);
});
$("set-card-thumb-size").addEventListener("change", async (e) => {
  previewCache.clear();
  await saveSetting({ card_thumb_size: Number(e.target.value) });
});
$("set-card-thumbs").addEventListener("change", (e) => saveSetting({ show_card_thumbnails: e.target.checked }));
$("set-card-counts").addEventListener("change", (e) => saveSetting({ show_card_counts: e.target.checked }));
$("set-image-fit").addEventListener("change", (e) => saveSetting({ image_fit: e.target.value }));
$("set-autosave").addEventListener("change", (e) => saveSetting({ autosave: e.target.checked }));
$("set-remember").addEventListener("change", (e) => saveSetting({ remember_last_project: e.target.checked }));
$("set-rescan").addEventListener("click", async () => {
  render(await post("/api/rescan"));
  toast("Folder rescanned.");
});

/* --------------------------------------------------------------- top bar */
/**
 * Ask the operating system for a folder. Falls back to the in-app browser
 * when there is no desktop to put a dialog on (a hosted server, say).
 */
async function chooseFolder({ title, start, onPick, confirmLabel }) {
  if (env.native_dialogs) {
    const result = await post("/api/pick-folder", { initial: start || "", title });
    if (result && result.supported) {
      if (result.path) onPick(result.path);
      return;
    }
    env.native_dialogs = false;     // do not keep trying
  }
  openBrowser({ title, start: start || env.home, mode: "folder",
                confirmLabel: confirmLabel || "Use this folder", onPick });
}

function chooseImageFolder() {
  chooseFolder({
    title: "Image folder",
    start: state.project.source_folder || env.home,
    onPick: async (picked) => render(await post("/api/folder", { path: picked })),
  });
}

$("btn-folder").addEventListener("click", chooseImageFolder);
$("btn-folder-empty").addEventListener("click", chooseImageFolder);

/* --------------------------------------------- zoom toolbar */
$("btn-zoom-in").addEventListener("click", () => {
  if (state.current && state.config.image_fit !== "actual") zoomIn();
});
$("btn-zoom-out").addEventListener("click", () => {
  if (state.current && state.config.image_fit !== "actual") zoomOut();
});
$("zoom-level").addEventListener("click", zoomReset);

/* --------------------------------------------- wheel zoom */
$("viewer").addEventListener("wheel", (event) => {
  if (!state || !state.current) return;
  if (state.config.image_fit === "actual") return;
  if (event.deltaY === 0) return;
  event.preventDefault();
  changeZoom(event.deltaY < 0 ? 1 : -1);
}, { passive: false });

/* --------------------------------------------- pan when zoomed */
$("viewer").addEventListener("pointerdown", (event) => {
  if (!zoomIsPanning && !$("viewer").classList.contains("zoomed")) return;
  if (event.button !== 1) return;
  if (event.target.closest(".zoom-toolbar")) return;
  zoomIsPanning = true;
  zoomPanStart = { x: event.clientX, y: event.clientY };
  const img = $("main-image");
  if (img) img.classList.add("panning");
  event.preventDefault();
});

document.addEventListener("pointermove", (event) => {
  if (!zoomIsPanning) return;
  event.preventDefault();
  const dx = event.clientX - zoomPanStart.x;
  const dy = event.clientY - zoomPanStart.y;
  zoomState.panX += dx;
  zoomState.panY += dy;
  zoomPanStart = { x: event.clientX, y: event.clientY };
  applyZoom();
});

document.addEventListener("pointerup", () => {
  if (zoomIsPanning) {
    zoomIsPanning = false;
    const img = $("main-image");
    if (img) img.classList.remove("panning");
  }
});

document.addEventListener("pointercancel", () => {
  if (zoomIsPanning) {
    zoomIsPanning = false;
    const img = $("main-image");
    if (img) img.classList.remove("panning");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && zoomIsPanning) {
    zoomIsPanning = false;
    const img = $("main-image");
    if (img) img.classList.remove("panning");
  }
});

function loadProject() {
  openBrowser({
    title: "Load project (.json)",
    start: state.project.path || env.home,
    mode: "file",
    confirmLabel: "Load",
    onPick: async (picked) => render(await post("/api/project/load", { path: picked })),
  });
}

async function saveProject() {
  if (state.project.path) {
    render(await post("/api/project/save", { path: state.project.path }));
    toast("Project saved.");
    return;
  }
  openBrowser({
    title: "Save project in folder",
    start: env.home,
    mode: "folder",
    confirmLabel: "Save here",
    onPick: async (folder) => {
      const name = await askText("Project file name", "sorting-project.json");
      if (!name) return;
      const separator = folder.includes("\\") ? "\\" : "/";
      render(await post("/api/project/save", { path: `${folder}${separator}${name}` }));
      toast("Project saved.");
    },
  });
}
$("btn-menu").addEventListener("click", (event) => {
  event.stopPropagation();
  openAppMenu();
});
$("btn-manage").addEventListener("click", () => openCategoryTable());
$("btn-skip").addEventListener("click", async () => render(await post("/api/skip")));
$("btn-undo").addEventListener("click", async () => render(await post("/api/undo")));
$("btn-apply").addEventListener("click", async () => render(await post("/api/apply")));
$("btn-discard").addEventListener("click", async () => {
  if (!await askConfirmation(`Throw away ${state.staged} waiting change(s)?\n\nThe images go back in the queue.`)) return;
  render(await post("/api/staged/discard"));
});

/* -------------------------------------------------------- global hotkeys */
document.addEventListener("keydown", async (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c"
      && window.getSelection()?.toString()) return;
  // Hotkey capture wins over everything else.
  if (capturingInput) {
    const hotkey = hotkeyFromEvent(event);
    if (!hotkey) return;
    event.preventDefault();
    const { input, row, onCommit } = capturingInput;
    input.value = event.key === "Escape" ? "" : hotkey;
    if (row) row.hotkey = input.value;
    input.dataset.previous = input.value;
    input.blur();
    if (onCommit) onCommit(input.value);
    return;
  }

  if (event.key === "Escape" && activeModal) { closeModal(); return; }

  const target = event.target;
  const typing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
  if (typing || activeModal) return;

  const ctrl = event.ctrlKey || event.metaKey;
  if (ctrl && event.key.toLowerCase() === "z") {
    event.preventDefault();
    render(await post("/api/undo"));
    return;
  }
  if (ctrl && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveProject();
    return;
  }
  if (ctrl && event.key.toLowerCase() === "o") {
    event.preventDefault();
    chooseImageFolder();
    return;
  }
  if (ctrl && event.key.toLowerCase() === "e") {
    event.preventDefault();
    openCategoryTable();
    return;
  }
  if (ctrl && event.key === "Enter" && state.staged) {
    event.preventDefault();
    if (!state.setup.ready) { openCategoryTable(); return; }
    render(await post("/api/apply"));
    return;
  }

  // Category hotkeys come from the live state, so a freshly added or edited
  // hotkey works straight away - no restart, no rebinding.
  const category = state.categories.find((c) => matchesHotkey(event, c.hotkey));
  if (category) {
    event.preventDefault();
    sortInto(category.id);
    return;
  }

  if (matchesHotkey(event, state.config.skip_hotkey)) {
    event.preventDefault();
    if (!state.setup.ready) { openCategoryTable(); return; }
    render(await post("/api/skip"));
    return;
  }

  if (event.ctrlKey || event.altKey || event.metaKey) return;

  if (state.current && state.config.image_fit !== "actual") {
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomIn();
      return;
    }
    if (event.key === "-") {
      event.preventDefault();
      zoomOut();
      return;
    }
    if (event.key === "0") {
      event.preventDefault();
      zoomReset();
      return;
    }
  }

  if (event.key === "ArrowLeft" || event.key === "Backspace") {
    event.preventDefault();
    render(await post("/api/undo"));
  } else if (event.key === "?") {
    event.preventDefault();
    openModal("modal-help");
  }
});

/* ------------------------------------------------------ dropping a folder */
function isFolderDrag(event) {
  return [...(event.dataTransfer?.items || [])].some((i) => i.kind === "file");
}

let dropDepth = 0;

function showDropOverlay(show) {
  $("drop-overlay").hidden = !show;
  $("dropzone")?.classList.toggle("over", show);
}

document.addEventListener("dragenter", (event) => {
  if (draggingImage !== null || !isFolderDrag(event)) return;
  dropDepth++;
  showDropOverlay(true);
});
document.addEventListener("dragleave", () => {
  if (dropDepth > 0 && --dropDepth === 0) showDropOverlay(false);
});
document.addEventListener("dragover", (event) => {
  if (draggingImage !== null || !isFolderDrag(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
});

document.addEventListener("drop", async (event) => {
  if (draggingImage !== null) return;
  dropDepth = 0;
  showDropOverlay(false);
  if (!event.dataTransfer) return;
  event.preventDefault();
  if (window.trimageNativeDrop && isFolderDrag(event)) return;
  await handleFolderDrop(event.dataTransfer);
});

async function handleNativeDrop(items) {
  dropDepth = 0;
  showDropOverlay(false);
  for (const item of items.filter((item) => item.directory)) {
    await loadDroppedFolder(item.path);
  }
  const paths = items.filter((item) => !item.directory).map((item) => item.path);
  if (paths.length) await loadDroppedImages(paths, []);
}

async function handleFolderDrop(transfer) {
  // A path dragged as text (from an address bar, say) is the easy case.
  const text = (transfer.getData("text/plain") || "").trim().replace(/^"|"$/g, "");
  if (text && /[\\/]/.test(text)) {
    const listing = await api(`/api/browse?path=${encodeURIComponent(text)}`);
    if (listing && !listing.error && listing.path === text) {
      await loadDroppedFolder(text);
      return;
    }
  }

  const entries = [...transfer.items]
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter(Boolean);
  const entry = entries.find((e) => e.isDirectory);

  if (!entry) {
    await handleImageDrop(entries, transfer);
    return;
  }

  // The browser hides the real path, so send the name and a few of the file
  // names and let the server find the folder on disk.
  const names = await readSomeNames(entry, 6);
  toast(`Looking for "${entry.name}"…`);
  const found = await post("/api/resolve-folder", { name: entry.name, files: names });
  const matches = (found && found.matches) || [];

  if (matches.length === 1) {
    await loadDroppedFolder(matches[0]);
  } else if (matches.length > 1) {
    openBrowser({
      title: `Which "${entry.name}"?`,
      start: matches[0],
      mode: "folder",
      confirmLabel: "Use this folder",
      onPick: (picked) => loadDroppedFolder(picked),
    });
    toast(`Found ${matches.length} folders called "${entry.name}" — pick one.`);
  } else {
    toast(`Could not find "${entry.name}" on disk — use the folder button instead.`, true);
  }
}

const IMAGE_SUFFIX = /\.(jpe?g|png|webp|gif|bmp|tiff?|avif|jfif)$/i;

/** A loose handful of images was dropped rather than a folder. */
/** A dropped folder joins what is loaded; the folder button replaces it. */
async function loadDroppedFolder(path) {
  if (!state.total) {
    render(await post("/api/folder", { path }));
    return;
  }
  const listing = await api(`/api/browse?path=${encodeURIComponent(path)}`);
  if (!listing) return;
  if (!listing.images) {
    toast("That folder has no images directly in it.", true);
    return;
  }
  const before = state.total;
  const result = await post("/api/folder/add", { path });
  if (!result || result.error) return;
  render(result);
  toast(`Added ${state.total - before} image(s) from ${path.split(/[\\/]/).pop()}.`);
}

async function handleImageDrop(entries, transfer) {
  let names = entries.filter((e) => e.isFile && IMAGE_SUFFIX.test(e.name))
                     .map((e) => e.name);
  if (!names.length && transfer.files) {
    names = [...transfer.files].map((f) => f.name).filter((n) => IMAGE_SUFFIX.test(n));
  }
  if (!names.length) {
    toast("Drop a folder, or some image files.", true);
    return;
  }

  toast(`Looking for ${names.length} image(s)…`);
  const found = await post("/api/resolve-files", { names });
  const paths = (found && found.paths) || [];
  const missing = (found && found.missing) || [];
  if (!paths.length) {
    toast("Could not find those images on disk — use the folder button instead.", true);
    return;
  }

  await loadDroppedImages(paths, missing);
}

async function loadDroppedImages(paths, missing) {
  // Dropping while something is already loaded adds to the list rather than
  // replacing it; the folder button is how you start over.
  const adding = state.total > 0;
  const before = state.total;
  const result = await post("/api/images", { paths, add: adding });
  if (!result || result.error) return;
  render(result);

  const added = state.total - before;
  const note = adding ? `Added ${added} image(s)` : `Loaded ${paths.length} image(s)`;
  toast(missing.length ? `${note}; ${missing.length} could not be found.` : `${note}.`,
        missing.length > 0);
}

function readSomeNames(entry, limit) {
  return new Promise((resolve) => {
    const reader = entry.createReader();
    reader.readEntries((entries) => {
      resolve(entries.filter((e) => e.isFile).slice(0, limit).map((e) => e.name));
    }, () => resolve([]));
  });
}

/* ------------------------------------------------------------ header fit */
const COMPACT_LEVELS = ["compact-1", "compact-2", "compact-3", "compact-4"];

/**
 * Keep the header on one row, whatever the window width. Drops the path width
 * first, then the words on the action buttons, then the word "Categories" -
 * and centres the action row in the window only when that fits.
 */
function fitHeader() {
  const bar = document.querySelector(".topbar");
  const left = document.querySelector(".topbar-left");
  const right = document.querySelector(".topbar-right");
  const middle = $("dock-controls");

  bar.classList.remove("centred", ...COMPACT_LEVELS);

  const gaps = 14 * 2;
  const padding = 28;
  const available = Math.min(bar.clientWidth, window.innerWidth);
  const needed = () =>
    left.scrollWidth + middle.scrollWidth + right.scrollWidth + gaps + padding;

  for (const level of COMPACT_LEVELS) {
    if (needed() <= available) break;
    bar.classList.add(level);
  }

  // Pin the middle group to the window centre only if both sides clear it.
  const half = available / 2;
  const widest = Math.max(left.scrollWidth, right.scrollWidth);
  if (widest + middle.scrollWidth / 2 + 16 <= half) bar.classList.add("centred");
}

/* -------------------------------------------------------------- resizing */
let dragging = null;

const cssPixels = (name) =>
  parseInt(getComputedStyle(document.documentElement).getPropertyValue(name), 10) || 0;
const setPixels = (name, value, min, max) =>
  document.documentElement.style.setProperty(
    name, `${Math.round(Math.max(min, Math.min(max, value)))}px`);

function startDrag(handle, axis, read, write, save) {
  handle.addEventListener("mousedown", (event) => {
    event.preventDefault();
    dragging = { start: axis === "x" ? event.clientX : event.clientY, from: read() };
    handle.classList.add("dragging");
    document.body.classList.add("resizing");

    const move = (e) => {
      const delta = (axis === "x" ? e.clientX : e.clientY) - dragging.start;
      write(dragging.from + (axis === "x" ? delta : -delta));
    };
    const stop = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", stop);
      handle.classList.remove("dragging");
      document.body.classList.remove("resizing");
      const value = read();
      dragging = null;
      save(value);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", stop);
  });
}

startDrag($("resize-strip"), "x",
  () => cssPixels("--strip"),
  (value) => setPixels("--strip", value, 80, 500),
  (value) => saveSetting({ filmstrip_size: value }));

startDrag($("resize-dock"), "y",
  () => cssPixels("--dock"),
  (value) => { setPixels("--dock", value, 132, 700); renderCards(); },
  (value) => saveSetting({ dock_height: value }));

let resizeTimer = null;
window.addEventListener("resize", () => {
  fitHeader();
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state) renderCards(); }, 120);
});

/* ----------------------------------------------------- carry on from last */
function offerResume() {
  const resume = state.resume;
  if (!resume || !resume.available) return;

  const summary = $("resume-summary");
  summary.replaceChildren();
  const bits = [];
  if (resume.categories) {
    bits.push(`${resume.categories} categor${resume.categories === 1 ? "y" : "ies"}`);
  }
  if (resume.source_folder) bits.push("an image folder");
  summary.append(document.createTextNode("Last time you had "));
  const bold = el("b");
  bold.textContent = bits.join(" and ");
  summary.append(bold);
  summary.append(document.createTextNode(
    resume.saved_at ? `, saved ${resume.saved_at}.` : "."));

  if (resume.source_folder) {
    const path = el("span", "path");
    path.textContent = resume.source_folder;
    summary.append(path);
  }
  openModal("modal-resume");
}

$("resume-yes").addEventListener("click", async () => {
  closeModal();
  render(await post("/api/resume"));
});
$("resume-no").addEventListener("click", async () => {
  closeModal();
  render(await post("/api/resume/dismiss"));
});

/* ------------------------------------------------------------------ boot */
(async function boot() {
  env = (await api("/api/env")) || env;
  await refresh();
  offerResume();
})();
