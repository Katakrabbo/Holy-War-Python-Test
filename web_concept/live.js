const ui = {
  state: null,
  selectedUid: null,
  drag: null,
  placement: null,
  targeting: null,
  contextCard: null,
  effectSelection: null,
  aiTimer: null,
  onlineTimer: null,
  onlineBusy: false,
  browserTimer: null,
  browserBusy: false,
  onlineStateKey: null,
  decisionId: null,
  runtimeSelectionOrder: [],
  deckEditor: null,
  deckDraft: null,
  deckEditorReturn: null,
  deckExportSelection: new Set(),
  deckValidationTimer: null,
  testEditor: null,
  testDraft: null,
  testStep: 0,
  testPicker: null,
  testStarted: false,
  config: null,
  options: null,
  optionsReturnTo: "main",
  joinTarget: null,
  onlinePhase: null
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

function showGameScreen() {
  $(".app-shell").hidden = false;
}

function hideGameScreen() {
  $(".app-shell").hidden = true;
}

async function api(path, payload) {
  const options = payload === undefined
    ? { headers: { Accept: "application/json" } }
    : {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload)
    };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || `Errore HTTP ${response.status}`);
  return data;
}

function cardTheme(type = "") {
  const normalized = type.toLocaleLowerCase("it");
  if (normalized.includes("santo") || normalized.includes("token")) return "saint";
  if (normalized.includes("artefatto")) return "artifact";
  if (normalized.includes("edificio")) return "building";
  if (normalized.includes("benedizione")) return "blessing";
  return "curse";
}

function cardByUid(uid) {
  if (!uid || !ui.state) return null;
  for (const player of ui.state.players) {
    const pools = [player.hand, player.graveyard, player.excommunicated, player.attack, player.defense, player.artifacts, [player.building]];
    for (const pool of pools) {
      const found = pool.find(card => card?.uid === uid);
      if (found && !found.hidden) return found;
    }
  }
  return null;
}

function setMessage(message, isError = false) {
  const live = $("#event-message");
  live.textContent = message || "";
  if (!message) return;
  let toast = $("#game-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "game-toast";
    document.body.append(toast);
  }
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("visible");
  clearTimeout(setMessage.timer);
  setMessage.timer = setTimeout(() => toast.classList.remove("visible"), 2600);
}

function previewStat(label, current, base) {
  if (current == null) return "";
  const currentNumber = Number(current);
  const baseNumber = Number(base);
  let tone = "";
  if (Number.isFinite(currentNumber) && Number.isFinite(baseNumber)) {
    if (currentNumber > baseNumber) tone = " stat-buffed";
    if (currentNumber < baseNumber) tone = " stat-debuffed";
  }
  const original = base == null ? "" : ` <small class="stat-base">(${base})</small>`;
  return `<span>${label} <b class="stat-current${tone}">${current}</b>${original}</span>`;
}

function showCard(card, element = null) {
  if (!card || card.hidden) return;
  ui.selectedUid = card.uid;
  $$(".game-card.selected, .mini-card.selected").forEach(node => node.classList.remove("selected"));
  element?.classList.add("selected");
  const preview = $("#card-preview");
  preview.className = `card-preview ${cardTheme(card.type)}`;
  $("#preview-type").textContent = card.type.toUpperCase();
  $("#preview-name").textContent = card.name;
  $("#preview-effect").textContent = card.effect || "Nessun testo effetto.";
  const stats = [`<span>Costo <b>${card.cost ?? "–"}</b></span>`];
  if (card.strength != null) stats.push(previewStat("Forza", card.strength, card.base_strength));
  if (card.faith != null) stats.push(previewStat("Fede", card.faith, card.base_faith));
  $("#preview-stats").innerHTML = stats.join("");
  $(".inspector").classList.add("open");
}

function makeUnit(card, side, token, label) {
  if (!card) {
    const empty = document.createElement("div");
    empty.className = "empty-slot unit";
    empty.dataset.dropTarget = side === "player" ? token : "";
    empty.innerHTML = `<span>${label}</span><em>Gioca qui</em>`;
    return empty;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = `game-card saint ${side === "player" ? "own-card" : "enemy-card"}`;
  if (card.can_activate) button.classList.add("effect-ready");
  if (card.exhausted) button.classList.add("exhausted");
  button.dataset.uid = card.uid;
  button.dataset.token = token;
  button.dataset.side = side;
  button.innerHTML = `<strong>${card.name}</strong><span class="stats">✦ ${card.strength ?? "–"}&nbsp;&nbsp; ◈ ${card.faith ?? "–"}</span>`;
  if (side === "player") button.draggable = true;
  button.addEventListener("click", () => selectOrTarget(card, button));
  button.addEventListener("contextmenu", event => openContextMenu(event, card, button));
  fitCardName(button.querySelector("strong"));
  return button;
}

function renderUnitRow(selector, cards, side, prefix, label) {
  const row = $(selector);
  row.replaceChildren(...cards.map((card, index) => makeUnit(card, side, `${prefix}${index + 1}`, `${label} ${index + 1}`)));
}

function makeSupport(card, side, token, className, building = false) {
  if (!card) {
    const empty = document.createElement("div");
    empty.className = `empty-slot ${building ? "building-slot " : ""}${className}`;
    empty.dataset.dropTarget = side === "player" ? token : "";
    empty.setAttribute("aria-label", `Slot ${building ? "edificio" : "artefatto"} libero`);
    return empty;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = `mini-card ${building ? "building" : "artifact"} ${className}`;
  if (card.can_activate) button.classList.add("effect-ready");
  button.dataset.uid = card.uid;
  button.dataset.token = token;
  button.dataset.side = side;
  button.innerHTML = `<span>${card.name}</span>`;
  button.addEventListener("click", () => selectOrTarget(card, button));
  button.addEventListener("contextmenu", event => openContextMenu(event, card, button));
  return button;
}

function renderSupports(selector, player, side) {
  const grid = $(selector);
  const positions = ["artifact-top-left", "artifact-top-right", "artifact-bottom-left", "artifact-bottom-right"];
  const children = player.artifacts.map((card, index) => makeSupport(card, side, `r${index + 1}`, positions[index]));
  children.splice(2, 0, makeSupport(player.building, side, "b", "building-tall", true));
  grid.replaceChildren(...children);
}

function makeHandCard(card) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "game-card hand-card";
  if (card.play_ready) button.classList.add("effect-ready");
  button.dataset.uid = card.uid;
  button.dataset.side = "player";
  button.draggable = true;
  const stats = card.strength != null
    ? `<span class="stats">✦ ${card.strength}&nbsp;&nbsp; ◈ ${card.faith ?? "–"}</span>`
    : `<span class="card-hint">Trascina o usa il tasto destro</span>`;
  button.innerHTML = `<small>${card.type.toUpperCase()} · <i class="inspiration-symbol" aria-hidden="true"></i> ${card.cost ?? "–"}</small><strong>${card.name}</strong>${stats}`;
  button.addEventListener("click", () => showCard(card, button));
  button.addEventListener("contextmenu", event => openContextMenu(event, card, button));
  return button;
}

function updateSummary(selector, player) {
  const panel = $(selector);
  panel.querySelector("h2").textContent = player.name;
  const values = panel.querySelectorAll(".resource-row b");
  values[0].textContent = player.sin;
  values[1].textContent = player.deck_count;
}

function updateZoneButtons(player, owner) {
  const values = {
    graveyard: player.graveyard.length,
    excommunicated: player.excommunicated.length
  };
  for (const [kind, count] of Object.entries(values)) {
    const button = $(`.inspectable-zone[data-zone-owner="${owner}"][data-zone-kind="${kind}"]`);
    button.querySelector("b").textContent = count;
    const locked = kind === "graveyard" ? player.graveyard_acts_as_deck : player.excommunicated_acts_as_deck;
    button.dataset.deckReplacement = String(locked);
    button.classList.toggle("zone-locked", locked);
    button.setAttribute("aria-disabled", String(locked));
  }
  const deck = $(`.zone-stack[aria-label="${owner === "player" ? "Le tue zone" : "Zone avversario"}"] .zone-slot:not(.inspectable-zone) b`);
  if (deck) deck.textContent = player.deck_count;
}

function renderEnemyHand(enemy) {
  const hand = $(".enemy-hand");
  const count = enemy.hand_count;
  const cards = Array.from({ length: count }, (_, index) => {
    const back = document.createElement("article");
    back.className = "card card-back";
    back.setAttribute("aria-label", "Carta avversaria coperta");
    const position = count <= 1 ? 0 : (index / (count - 1)) * 2 - 1;
    back.style.setProperty("--fan-angle", `${position * 11}deg`);
    back.style.setProperty("--fan-y", `${Math.abs(position) * 6}px`);
    return back;
  });
  const caption = document.createElement("span");
  caption.className = "zone-caption";
  caption.textContent = `Mano avversario · ${enemy.hand_count} carte`;
  hand.replaceChildren(...cards, caption);
}

function renderLog(logs) {
  const list = $("#match-log .game-log");
  list.replaceChildren(...[...logs].reverse().map((message, index) => {
    const item = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = index === 0 ? "Adesso" : "Prima";
    item.append(time, document.createTextNode(message));
    return item;
  }));
}

function render(data) {
  if (!data?.game) return;
  showGameScreen();
  ui.state = data.game;
  const player = ui.state.players[0];
  const enemy = ui.state.players[1];
  $("#preparation-fog").hidden = !enemy.field_hidden;
  updateSummary(".own-summary", player);
  updateSummary(".opponent-summary", enemy);
  updateZoneButtons(player, "player");
  updateZoneButtons(enemy, "opponent");
  renderEnemyHand(enemy);
  renderUnitRow(".enemy-defense-line .unit-row", enemy.defense, "opponent", "d", "Difesa");
  renderUnitRow(".enemy-attack-line .unit-row", enemy.attack, "opponent", "a", "Attacco");
  renderUnitRow(".player-attack-line .unit-row", player.attack, "player", "a", "Attacco");
  renderUnitRow(".player-defense-line .unit-row", player.defense, "player", "d", "Difesa");
  renderSupports(".enemy-support", enemy, "opponent");
  renderSupports(".own-support", player, "player");
  const hand = $(".hand-cards");
  hand.style.setProperty("--hand-count", String(Math.max(1, player.hand.length)));
  hand.replaceChildren(...player.hand.map(makeHandCard));
  renderLog(ui.state.logs);

  const active = ui.state.players[ui.state.active_player];
  $("#turn-label").textContent = ui.state.winner == null
    ? (ui.state.active_player === 0 ? "Il tuo turno" : `Turno di ${active.name}`)
    : `${ui.state.players[ui.state.winner].name} ha vinto`;
  $("#phase-label").textContent = `${ui.state.preparation ? "Preparazione" : ui.state.phase} · Turno ${ui.state.turn}`;
  $("#inspiration-owner").textContent = active.name;
  $("#inspiration-value").textContent = active.inspiration;
  const maxInspiration = Math.max(10, active.inspiration);
  $("#inspiration-gauge").style.setProperty("--value", String((active.inspiration / maxInspiration) * 100));
  $("#inspiration-gauge").setAttribute("aria-valuenow", String(active.inspiration));
  $("#end-turn-button").disabled = !ui.state.can_act;
  $("#end-turn-button").textContent = ui.state.can_act ? "Termina turno" : "Attendi…";
  const chainPass = $("#chain-pass-button");
  chainPass.hidden = !ui.state.chain?.active || ui.state.chain.priority !== 0;
  $("#end-turn-button").hidden = Boolean(ui.state.chain?.active);
  const chainEnabled = ui.state.chain?.enabled !== false;
  $("#chain-enable-button").setAttribute("aria-pressed", String(chainEnabled));
  $("#chain-disable-button").setAttribute("aria-pressed", String(!chainEnabled));
  $("#chain-enable-button").disabled = chainEnabled;
  $("#chain-disable-button").disabled = !chainEnabled;
  if (ui.state.chain?.active) {
    $("#turn-label").textContent = ui.state.chain.priority === 0 ? "Priorità: rispondi o passa" : "Catena avversaria";
  }

  const coin = ui.state.coin_toss;
  const coinDialog = $("#coin-toss-dialog");
  if (coin?.pending) {
    $("#coin-toss-message").textContent = `${coin.winner_name} ha vinto il lancio della moneta e inizierà per primo.`;
    $("#coin-toss-wait").hidden = !coin.confirmed;
    $("#confirm-coin-toss").hidden = coin.confirmed;
    if (!coinDialog.open) coinDialog.showModal();
  } else if (coinDialog.open) {
    coinDialog.close();
  }

  if (ui.selectedUid) {
    const selected = cardByUid(ui.selectedUid);
    if (selected) showCard(selected, $(`[data-uid="${CSS.escape(ui.selectedUid)}"]`));
  }
  renderRuntimeDecision(ui.state.decision);
  scheduleAiStep();
}

function scheduleAiStep() {
  clearTimeout(ui.aiTimer);
  ui.aiTimer = null;
  if (!ui.state?.ai_pending || ui.state?.decision) return;
  ui.aiTimer = setTimeout(async () => {
    try {
      const data = await api("/api/ai-step", {});
      render(data);
      if (data.message && data.message !== "AI passa.") setMessage(data.message, !data.ok);
    } catch (error) {
      setMessage(error.message, true);
    }
  }, 1000);
}

function showEffectChoicePreview(card, selector) {
  if (!card) return;
  const preview = $(selector);
  preview.className = `effect-choice-preview ${cardTheme(card.type)}`;
  preview.querySelector(".effect-preview-type").textContent = `${card.type.toUpperCase()}${card.expansion ? ` · ${card.expansion}` : ""}`;
  preview.querySelector("h3").textContent = card.name;
  const stats = [
    `<span title="Ispirazione richiesta"><i class="inspiration-symbol" aria-hidden="true"></i> Ispirazione <b>${card.cost ?? "–"}</b></span>`,
    `<span title="Attacco">✦ ATK <b>${card.strength ?? "–"}</b></span>`,
    `<span title="Fede">◈ Fede <b>${card.faith ?? "–"}</b></span>`,
    `<span title="Croci">Croci <b>${card.crosses ?? "–"}</b></span>`
  ];
  preview.querySelector(".effect-preview-stats").innerHTML = stats.join("");
  preview.querySelector(".effect-preview-text p").textContent = card.effect || "Nessun testo effetto.";
}

function resetEffectChoicePreview(selector) {
  const preview = $(selector);
  preview.className = "effect-choice-preview";
  preview.querySelector(".effect-preview-type").textContent = "ANTEPRIMA CARTA";
  preview.querySelector("h3").textContent = "Passa sopra una carta";
  preview.querySelector(".effect-preview-stats").replaceChildren();
  preview.querySelector(".effect-preview-text p").textContent = "Qui vedrai tutte le informazioni della carta prima di selezionarla.";
}

function makeEffectChoiceContent(option, previewSelector) {
  if (!option.card) return document.createTextNode(option.label);
  const content = document.createElement("span");
  content.className = "effect-choice-card";
  const name = document.createElement("strong");
  name.textContent = option.card.name;
  const location = document.createElement("small");
  location.textContent = option.label.includes(" · ") ? option.label.split(" · ").slice(1).join(" · ") : option.label;
  const stats = document.createElement("span");
  stats.className = "effect-choice-stats";
  stats.innerHTML = [
    `<span title="Ispirazione"><i class="inspiration-symbol" aria-hidden="true"></i> ${option.card.cost ?? "–"}</span>`,
    `<span title="Attacco">✦ ${option.card.strength ?? "–"}</span>`,
    `<span title="Fede">◈ ${option.card.faith ?? "–"}</span>`
  ].join("");
  content.append(name, location, stats);
  content.addEventListener("mouseenter", () => showEffectChoicePreview(option.card, previewSelector));
  return content;
}

function renderRuntimeDecision(decision) {
  const dialog = $("#runtime-decision-dialog");
  if (!decision) {
    ui.decisionId = null;
    ui.runtimeSelectionOrder = [];
    if (dialog.open) dialog.close();
    return;
  }
  if (ui.decisionId === decision.id && dialog.open) return;
  ui.decisionId = decision.id;
  ui.runtimeSelectionOrder = [];
  $("#runtime-decision-title").textContent = decision.title || "Scelta richiesta";
  $("#runtime-decision-prompt").textContent = decision.prompt || "Completa la scelta per continuare.";
  resetEffectChoicePreview("#runtime-choice-preview");
  const options = $("#runtime-decision-options");
  options.classList.toggle("reveal-choice-list", decision.kind === "reveal");
  $("#confirm-runtime-decision").textContent = decision.kind === "reveal" ? "Continua" : (decision.kind === "summon_slot" ? "Evoca qui" : "Conferma");
  if (decision.kind === "reveal" && decision.revealed_card) {
    const card = decision.revealed_card;
    const revealed = document.createElement("article");
    revealed.className = "revealed-effect-card";
    revealed.tabIndex = 0;
    revealed.innerHTML = `<small>${card.type.toUpperCase()} · ${card.expansion || ""}</small><strong>${card.name}</strong><span class="effect-choice-stats"><span title="Ispirazione"><i class="inspiration-symbol" aria-hidden="true"></i> ${card.cost ?? "–"}</span><span title="Attacco">✦ ${card.strength ?? "–"}</span><span title="Fede">◈ ${card.faith ?? "–"}</span></span>`;
    const preview = () => showEffectChoicePreview(card, "#runtime-choice-preview");
    revealed.addEventListener("mouseenter", preview);
    revealed.addEventListener("focus", preview);
    options.replaceChildren(revealed);
    showEffectChoicePreview(card, "#runtime-choice-preview");
  } else {
    options.replaceChildren(...decision.options.map((option, index) => {
      const label = document.createElement("label");
      label.className = "effect-choice";
      const input = document.createElement("input");
      input.type = decision.maximum === 1 ? "radio" : "checkbox";
      input.name = "runtime-decision-option";
      input.dataset.value = JSON.stringify(option.value);
      input.addEventListener("change", () => {
        const value = JSON.parse(input.dataset.value);
        ui.runtimeSelectionOrder = ui.runtimeSelectionOrder.filter(item => item !== value);
        if (input.checked) ui.runtimeSelectionOrder.push(value);
      });
      if (option.card) {
        label.addEventListener("mouseenter", () => showEffectChoicePreview(option.card, "#runtime-choice-preview"));
        input.addEventListener("focus", () => showEffectChoicePreview(option.card, "#runtime-choice-preview"));
      }
      if (index === 0 && decision.kind === "confirm") input.checked = true;
      label.append(input, makeEffectChoiceContent(option, "#runtime-choice-preview"));
      return label;
    }));
  }
  const firstCard = decision.options.find(option => option.card)?.card;
  if (firstCard) showEffectChoicePreview(firstCard, "#runtime-choice-preview");
  $("#cancel-runtime-decision").hidden = !decision.allow_cancel;
  if (!dialog.open) dialog.showModal();
}

async function submitRuntimeDecision(answer) {
  const decision = ui.state?.decision;
  if (!decision) return;
  try {
    const data = await api("/api/decision", { id: decision.id, answer });
    ui.decisionId = null;
    if ($("#runtime-decision-dialog").open) $("#runtime-decision-dialog").close();
    render(data);
    setMessage(data.message, !data.ok);
  } catch (error) {
    setMessage(error.message, true);
  }
}

$("#runtime-decision-form").addEventListener("submit", event => {
  event.preventDefault();
  const decision = ui.state?.decision;
  if (!decision) return;
  if (decision.kind === "reveal") {
    submitRuntimeDecision("__continue__");
    return;
  }
  const checked = $$('#runtime-decision-options input:checked');
  if (checked.length < decision.minimum || checked.length > decision.maximum) {
    setMessage(`Seleziona da ${decision.minimum} a ${decision.maximum} opzioni.`, true);
    return;
  }
  const values = decision.preserve_order
    ? ui.runtimeSelectionOrder.slice()
    : checked.map(input => JSON.parse(input.dataset.value));
  submitRuntimeDecision(decision.maximum === 1 ? values[0] : values);
});
$("#cancel-runtime-decision").addEventListener("click", () => submitRuntimeDecision(null));
$("#runtime-decision-dialog").addEventListener("cancel", event => event.preventDefault());

function fitCardName(label) {
  if (!label) return;
  const length = Array.from(label.textContent.trim()).length;
  if (length >= 24) label.classList.add("name-very-long");
  else if (length >= 18) label.classList.add("name-long");
}

async function sendAction(payload) {
  clearInteractionState();
  try {
    const data = await api("/api/action", payload);
    render(data);
    setMessage(data.message, !data.ok);
    return data.ok;
  } catch (error) {
    setMessage(error.message, true);
    return false;
  }
}

function validPlayTargets(card) {
  const type = card.type.toLocaleLowerCase("it");
  if (type.includes("santo") || type.includes("token")) return ["a1", "a2", "a3", "d1", "d2", "d3"];
  if (type.includes("artefatto")) return ["r1", "r2", "r3", "r4"];
  if (type.includes("edificio")) return ["b"];
  return [];
}

document.addEventListener("dragstart", event => {
  const source = event.target.closest("[data-uid]");
  if (!source || !ui.state?.can_act) return event.preventDefault();
  const card = cardByUid(source.dataset.uid);
  if (!card) return event.preventDefault();
  if (source.matches(".hand-card")) {
    const targets = validPlayTargets(card);
    if (!targets.length) return event.preventDefault();
    ui.drag = { type: "play", uid: card.uid, targets };
    $$('[data-drop-target]').filter(node => targets.includes(node.dataset.dropTarget)).forEach(node => node.classList.add("drop-valid"));
  } else if (source.dataset.side === "player" && source.closest(".player-attack-line, .player-defense-line")) {
    const targets = card.attack_targets || [];
    if (!targets.length) return event.preventDefault();
    ui.drag = { type: "attack", source: source.dataset.token, targets };
    if (targets.includes("direct")) {
      $("[data-direct-attack]").classList.add("attack-target");
    }
    $$(".enemy-attack-line [data-uid]")
      .filter(node => targets.includes(node.dataset.token))
      .forEach(node => node.classList.add("drop-valid", "attack-target"));
  } else {
    return event.preventDefault();
  }
  source.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", card.uid);
});

function resolveDropElement(event) {
  const exact = event.target.closest("[data-drop-target], .attack-target, [data-direct-attack]");
  if (exact) return exact;
  if (ui.drag?.type !== "attack" || !event.target.closest(".enemy-attack-line")) return null;
  const candidates = $$(".enemy-attack-line .attack-target");
  if (!candidates.length) return null;
  return candidates.reduce((nearest, candidate) => {
    const rect = candidate.getBoundingClientRect();
    const distance = Math.abs(event.clientX - (rect.left + rect.width / 2));
    return !nearest || distance < nearest.distance ? { element: candidate, distance } : nearest;
  }, null)?.element || null;
}

document.addEventListener("dragover", event => {
  if (!ui.drag) return;
  const target = resolveDropElement(event);
  const token = target?.dataset.directAttack || target?.dataset.dropTarget || target?.dataset.token;
  if (!target || !ui.drag.targets.includes(token)) return;
  event.preventDefault();
  $$(".drop-hover").forEach(node => node.classList.remove("drop-hover"));
  target.classList.add("drop-hover");
});

document.addEventListener("dragleave", event => event.target.closest(".drop-hover")?.classList.remove("drop-hover"));

document.addEventListener("drop", event => {
  if (!ui.drag) return;
  const target = resolveDropElement(event);
  const token = target?.dataset.directAttack || target?.dataset.dropTarget || target?.dataset.token;
  if (!target || !ui.drag.targets.includes(token)) return;
  event.preventDefault();
  if (ui.drag.type === "play") {
    const card = cardByUid(ui.drag.uid);
    if (card) beginPlay(card, token);
  } else {
    sendAction({ type: "attack", source: ui.drag.source, target: token === "direct" ? null : token });
  }
});

document.addEventListener("dragend", clearInteractionState);

function clearInteractionState() {
  $$(".drop-valid, .drop-hover, .attack-target, .dragging").forEach(node => node.classList.remove("drop-valid", "drop-hover", "attack-target", "dragging"));
  ui.drag = null;
  ui.placement = null;
  cancelTargeting();
}

function startPlacement(card) {
  clearInteractionState();
  const targets = validPlayTargets(card);
  ui.placement = { card, targets };
  $$('[data-drop-target]').filter(node => targets.includes(node.dataset.dropTarget))
    .forEach(node => node.classList.add("drop-valid"));
  setMessage("Scegli uno slot illuminato oppure trascina la carta dalla mano.");
}

document.addEventListener("click", event => {
  if (!ui.placement) return;
  const slot = event.target.closest("[data-drop-target]");
  if (!slot || !ui.placement.targets.includes(slot.dataset.dropTarget)) return;
  const { card } = ui.placement;
  const placement = slot.dataset.dropTarget;
  clearInteractionState();
  beginPlay(card, placement);
});

function selectOrTarget(card, element) {
  if (ui.targeting) {
    if (!element?.classList.contains("effect-target")) {
      setMessage("Questa carta non e un bersaglio valido.", true);
      return;
    }
    setTarget(card.uid, element);
    return;
  }
  showCard(card, element);
}

function setTarget(uid, element = null) {
  if (!ui.targeting) return;
  $$(".target-selected").forEach(node => node.classList.remove("target-selected"));
  element?.classList.add("target-selected");
  ui.targeting.target = element?.dataset.token || uid;
  $("#targeting-count").textContent = "1/1";
  $("#confirm-targets-button").disabled = false;
}

function startTargeting(action) {
  ui.targeting = { ...action, target: null };
  $$(".battlefield [data-uid]")
    .filter(node => node.dataset.uid !== action.uid)
    .filter(node => action.targetMode !== "own_saint" || (node.dataset.side === "player" && /^[ad]/.test(node.dataset.token)))
    .filter(node => action.targetMode !== "opponent_saint" || (node.dataset.side === "enemy" && /^[ad]/.test(node.dataset.token)))
    .forEach(node => node.classList.add("effect-target"));
  $("#targeting-title").textContent = "Scegli un bersaglio oppure conferma senza bersaglio";
  $("#targeting-count").textContent = "0/1";
  $("#confirm-targets-button").disabled = false;
  $("#targeting-toolbar").hidden = false;
}

function cancelTargeting() {
  $$(".effect-target, .target-selected").forEach(node => node.classList.remove("effect-target", "target-selected"));
  $("#targeting-toolbar").hidden = true;
  ui.targeting = null;
}

$("#confirm-targets-button").addEventListener("click", () => {
  if (!ui.targeting) return;
  const action = ui.targeting;
  const payload = action.kind === "play"
    ? { type: "play", uid: action.uid, target: action.target }
    : { type: "activate", source: action.source, target: action.target };
  sendAction(payload);
});
$("#cancel-targets-button").addEventListener("click", cancelTargeting);

function openContextMenu(event, card, element) {
  event.preventDefault();
  showCard(card, element);
  ui.contextCard = { card, element };
  const menu = $("#card-context-menu");
  const isHand = element.matches(".hand-card");
  $("#context-card-name").textContent = card.name;
  $("#activate-effect-button").textContent = isHand ? "Gioca carta" : "Attiva effetto";
  $("#activate-effect-button").disabled = !isHand && !card.can_activate;
  menu.hidden = false;
  menu.style.left = `${Math.max(8, Math.min(event.clientX, innerWidth - 205))}px`;
  menu.style.top = `${Math.max(8, Math.min(event.clientY, innerHeight - 115))}px`;
}

function openEffectSelection(card, steps, action) {
  ui.effectSelection = { card, steps, action };
  resetEffectChoicePreview("#effect-choice-preview");
  $("#effect-selection-title").textContent = card.name;
  $("#effect-selection-summary").textContent = steps.length === 1
    ? "Scegli le carte richieste dall'effetto nella zona indicata."
    : "Completa in ordine tutte le scelte richieste dall'effetto.";
  const container = $("#effect-selection-steps");
  container.replaceChildren(...steps.map((step, stepIndex) => {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "effect-selection-step";
    const legend = document.createElement("legend");
    legend.textContent = steps.length > 1 ? `Scelta ${stepIndex + 1} · ${step.zone}` : step.zone;
    const rule = document.createElement("p");
    rule.className = "effect-selection-rule";
    rule.textContent = step.minimum === step.maximum
      ? `Seleziona ${step.minimum} ${step.minimum === 1 ? "carta" : "carte"}.`
      : `Seleziona da ${step.minimum} a ${step.maximum} carte.`;
    const list = document.createElement("div");
    list.className = "effect-choice-list";
    if (!step.candidates.length) {
      const empty = document.createElement("div");
      empty.className = "effect-selection-empty";
      empty.textContent = "Nessuna carta valida disponibile in questa zona.";
      list.append(empty);
    } else {
      step.candidates.forEach(candidate => {
        const label = document.createElement("label");
        label.className = "effect-choice";
        const input = document.createElement("input");
        input.type = step.maximum === 1 ? "radio" : "checkbox";
        input.name = `effect-step-${stepIndex}`;
        input.value = candidate.value;
        input.addEventListener("change", () => {
          const checked = $$(`input[name="effect-step-${stepIndex}"]:checked`);
          if (checked.length > step.maximum) {
            input.checked = false;
            setMessage(`Puoi scegliere al massimo ${step.maximum} carte.`, true);
          }
        });
        if (candidate.card) {
          label.addEventListener("mouseenter", () => showEffectChoicePreview(candidate.card, "#effect-choice-preview"));
          input.addEventListener("focus", () => showEffectChoicePreview(candidate.card, "#effect-choice-preview"));
        }
        label.append(input, makeEffectChoiceContent(candidate, "#effect-choice-preview"));
        list.append(label);
      });
    }
    fieldset.append(legend, rule, list);
    return fieldset;
  }));
  const firstCard = steps.flatMap(step => step.candidates).find(candidate => candidate.card)?.card;
  if (firstCard) showEffectChoicePreview(firstCard, "#effect-choice-preview");
  $("#confirm-effect-selection").disabled = steps.some(step => step.candidates.length < step.minimum || step.maximum < step.minimum);
  $("#effect-selection-dialog").showModal();
}

async function beginPlay(card, placement = "") {
  if (!placement && validPlayTargets(card).length) {
    startPlacement(card);
    return;
  }
  try {
    const options = await api("/api/play-options", { uid: card.uid, placement });
    if (options.steps.length) {
      openEffectSelection(card, options.steps, {
        kind: "play", uid: card.uid, placement: options.placement, formatter: options.formatter, targetPrefix: options.target_prefix
      });
    } else if (card.play_requires_target) {
      // Compatibility path for the few legacy scripts that still use a
      // board-token targeting mode instead of a TargetSpec.
      startTargeting({ kind: "play", uid: card.uid, targetMode: card.play_targeting });
    } else {
      sendAction({ type: "play", uid: card.uid, target: placement || null });
    }
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function beginActivation(card, source) {
  try {
    const options = await api("/api/activate-options", { source });
    if (options.steps.length) {
      openEffectSelection(card, options.steps, { kind: "activate", uid: card.uid, source });
    } else if (options.legacy_requires_target) {
      startTargeting({ kind: "activate", uid: card.uid, source });
    } else {
      sendAction({ type: "activate", source });
    }
  } catch (error) {
    setMessage(error.message, true);
  }
}

$("#effect-selection-form").addEventListener("submit", event => {
  event.preventDefault();
  const selection = ui.effectSelection;
  if (!selection) return;
  const values = [];
  for (let index = 0; index < selection.steps.length; index += 1) {
    const step = selection.steps[index];
    const chosen = $$(`input[name="effect-step-${index}"]:checked`).map(input => input.value);
    if (chosen.length < step.minimum || chosen.length > step.maximum) {
      setMessage(`La scelta ${index + 1} richiede da ${step.minimum} a ${step.maximum} carte.`, true);
      return;
    }
    values.push({ actionIndex: step.action_index, value: chosen.join(",") });
  }
  let target;
  if (selection.action.formatter === "named_steps") {
    target = `${selection.action.targetPrefix}:${values.map((item, index) => `${selection.steps[index].key}=${item.value}`).join(";")}`;
  } else if (selection.action.formatter === "sacrifice") {
    const sacrifices = values.find((item, index) => selection.steps[index]?.key === "sacrifice")?.value || "";
    target = `${selection.action.placement || ""}|sac:${sacrifices}`;
  } else {
    target = values.length === 1
      ? values[0].value
      : `seq:${values.map(item => `${item.actionIndex}=${item.value}`).join(";;")}`;
  }
  $("#effect-selection-dialog").close();
  ui.effectSelection = null;
  const payload = selection.action.kind === "play"
    ? { type: "play", uid: selection.action.uid, target }
    : { type: "activate", source: selection.action.source, target };
  sendAction(payload);
});

$("#activate-effect-button").addEventListener("click", () => {
  const context = ui.contextCard;
  $("#card-context-menu").hidden = true;
  if (!context) return;
  if (context.element.matches(".hand-card")) {
    beginPlay(context.card);
  }
  else {
    const source = context.element.dataset.side === "enemy"
      ? `enemy:${context.element.dataset.token}`
      : context.element.dataset.token;
    beginActivation(context.card, source);
  }
});
$("#inspect-card-button").addEventListener("click", () => {
  if (ui.contextCard) showCard(ui.contextCard.card, ui.contextCard.element);
  $("#card-context-menu").hidden = true;
});
document.addEventListener("pointerdown", event => {
  if (!event.target.closest("#card-context-menu")) $("#card-context-menu").hidden = true;
});

function zoneCards(owner, kind) {
  const player = ui.state.players[owner === "player" ? 0 : 1];
  return kind === "graveyard" ? player.graveyard : player.excommunicated;
}

function showZoneDetail(card, button) {
  $$(".zone-card-entry.active").forEach(node => node.classList.remove("active"));
  button?.classList.add("active");
  $("#zone-preview-type").textContent = card.type.toUpperCase();
  $("#zone-preview-name").textContent = card.name;
  $("#zone-preview-effect").textContent = card.effect || "Nessun testo effetto.";
  $("#zone-preview-stats").innerHTML = `<span>Costo <b>${card.cost ?? "–"}</b></span>${card.strength != null ? `<span>Forza <b>${card.strength}</b></span><span>Fede <b>${card.faith ?? "–"}</b></span>` : ""}`;
}

function openZone(zone) {
  if (!ui.state || zone.dataset.deckReplacement === "true") return;
  const owner = zone.dataset.zoneOwner;
  const kind = zone.dataset.zoneKind;
  const contents = zoneCards(owner, kind);
  $("#zone-dialog-owner").textContent = owner === "player" ? "LE TUE CARTE" : "CARTE AVVERSARIE";
  $("#zone-dialog-title").textContent = kind === "graveyard" ? "Cimitero" : "Carte scomunicate";
  $("#zone-dialog-summary").textContent = `${contents.length} ${contents.length === 1 ? "carta" : "carte"} in questa zona.`;
  const list = $("#zone-card-list");
  const detail = $("#zone-card-detail");
  list.replaceChildren();
  detail.hidden = contents.length === 0;
  if (!contents.length) {
    const item = document.createElement("li");
    item.className = "empty-zone-message";
    item.textContent = "Questa zona è vuota.";
    list.append(item);
  } else {
    contents.forEach((card, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      item.style.setProperty("--stack-index", String(index + 1));
      button.className = "zone-card-entry";
      button.type = "button";
      button.innerHTML = `<small>${card.type}</small><strong>${card.name}</strong>`;
      button.addEventListener("mouseenter", () => showZoneDetail(card, button));
      button.addEventListener("focus", () => showZoneDetail(card, button));
      button.addEventListener("click", () => {
        showZoneDetail(card, button);
        if (ui.targeting) {
          setTarget(card.uid);
          $("#zone-dialog").close();
          setMessage(`${card.name} selezionata come bersaglio.`);
        }
      });
      item.append(button);
      list.append(item);
    });
    showZoneDetail(contents[0], list.querySelector("button"));
  }
  $("#zone-dialog").showModal();
}

$$(".inspectable-zone").forEach(zone => zone.addEventListener("click", () => openZone(zone)));

$("#end-turn-button").addEventListener("click", () => sendAction({ type: "end_turn" }));
$("#chain-pass-button").addEventListener("click", () => sendAction({ type: "chain_pass" }));
$("#chain-enable-button").addEventListener("click", () => sendAction({ type: "set_chain", enabled: true }));
$("#chain-disable-button").addEventListener("click", () => sendAction({ type: "set_chain", enabled: false }));
async function returnToMainMenu() {
  clearTimeout(ui.onlineTimer);
  clearTimeout(ui.browserTimer);
  if (ui.state?.mode === "online") {
    try { await api("/api/multiplayer/leave", {}); } catch (_) { /* navigation must still work */ }
  }
  ["#pause-dialog", "#surrender-dialog", "#rematch-dialog", "#coin-toss-dialog", "#online-room-dialog", "#online-browser-dialog"]
    .forEach(selector => { const dialog = $(selector); if (dialog?.open) dialog.close(); });
  ui.onlineStateKey = null;
  ui.onlinePhase = null;
  openMainMenu();
}
$("#new-game-button").addEventListener("click", returnToMainMenu);

function fillDeckSelect(select, decks, selectedId) {
  const groups = new Map();
  decks.forEach(deck => {
    if (!groups.has(deck.religion)) groups.set(deck.religion, []);
    groups.get(deck.religion).push(deck);
  });
  select.replaceChildren(...[...groups].map(([religion, entries]) => {
    const group = document.createElement("optgroup");
    group.label = religion;
    entries.forEach(deck => {
      const option = document.createElement("option");
      option.value = deck.id;
      option.textContent = deck.name;
      option.selected = deck.id === selectedId;
      group.append(option);
    });
    return group;
  }));
}

function refreshDeckSelects(config) {
  const player = $("#player-deck");
  const opponent = $("#opponent-deck");
  const currentPlayer = player.value || config.defaults.player_deck;
  const currentOpponent = opponent.value || config.defaults.opponent_deck;
  fillDeckSelect(player, config.decks, config.decks.some(deck => deck.id === currentPlayer) ? currentPlayer : config.defaults.player_deck);
  fillDeckSelect(opponent, config.decks, config.decks.some(deck => deck.id === currentOpponent) ? currentOpponent : config.defaults.opponent_deck);
  if ($("#online-player-deck")) fillDeckSelect($("#online-player-deck"), config.decks, currentPlayer);
  if ($("#option-default-deck")) fillDeckSelect($("#option-default-deck"), config.decks, currentPlayer);
}

function preferredDeckId() {
  const saved = ui.options?.default_deck;
  return ui.config?.decks?.some(deck => deck.id === saved) ? saved : ui.config?.defaults?.player_deck;
}

function freshDeckDraft() {
  return { id: null, name: "", religion: ui.deckEditor?.religions?.[0] || "", cards: new Map() };
}

function loadDeckDraft(deck = null) {
  ui.deckDraft = freshDeckDraft();
  if (deck) {
    ui.deckDraft.id = deck.id;
    ui.deckDraft.name = deck.name;
    ui.deckDraft.religion = deck.religion;
    (deck.cards || []).forEach(entry => ui.deckDraft.cards.set(entry.name, Number(entry.qty) || 0));
  }
  $("#deck-editor-name").value = ui.deckDraft.name;
  $("#deck-editor-religion").value = ui.deckDraft.religion;
  $("#deck-delete-button").disabled = !ui.deckDraft.id;
  renderDeckLibrary();
  renderDeckLists();
}

function renderDeckLibrary() {
  const list = $("#deck-saved-list");
  list.replaceChildren();
  const availableIds = new Set((ui.deckEditor?.decks || []).map(deck => deck.id));
  ui.deckExportSelection = new Set([...ui.deckExportSelection].filter(id => availableIds.has(id)));
  (ui.deckEditor?.decks || []).forEach(deck => {
    const row = document.createElement("div");
    row.className = "deck-saved-entry-row";
    const selection = document.createElement("input");
    selection.type = "checkbox";
    selection.className = "deck-export-checkbox";
    selection.checked = ui.deckExportSelection.has(deck.id);
    selection.setAttribute("aria-label", `Seleziona ${deck.name} per l'esportazione`);
    selection.addEventListener("change", () => {
      if (selection.checked) ui.deckExportSelection.add(deck.id);
      else ui.deckExportSelection.delete(deck.id);
      updateDeckExportControls();
    });
    const button = document.createElement("button");
    button.type = "button";
    button.className = `deck-saved-entry${deck.id === ui.deckDraft?.id ? " active" : ""}`;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", deck.id === ui.deckDraft?.id ? "true" : "false");
    const name = document.createElement("strong");
    name.textContent = deck.name;
    const religion = document.createElement("small");
    religion.textContent = deck.religion;
    button.append(name, religion);
    button.addEventListener("click", () => loadDeckDraft(deck));
    row.append(selection, button);
    list.append(row);
  });
  updateDeckExportControls();
}

function updateDeckExportControls() {
  const count = ui.deckExportSelection.size;
  const allDecks = ui.deckEditor?.decks || [];
  $("#deck-export-button").disabled = count === 0;
  $("#deck-export-button").textContent = `Esporta (${count})`;
  $("#deck-select-all").checked = allDecks.length > 0 && count === allDecks.length;
  $("#deck-select-all").indeterminate = count > 0 && count < allDecks.length;
}

function showDeckCardInfo(card) {
  const info = $("#deck-card-info");
  info.replaceChildren();
  const label = document.createElement("small");
  label.textContent = `${card.card_type} · ${card.expansion || "Neutre"}`;
  const name = document.createElement("strong");
  name.textContent = card.name;
  const effect = document.createElement("p");
  const stats = [`Croci ${card.crosses || "–"}`];
  if (card.strength != null) stats.push(`Forza ${card.strength}`);
  if (card.faith != null) stats.push(`Fede ${card.faith}`);
  effect.textContent = `${stats.join(" · ")} — ${card.effect_text || "Nessun testo effetto."}`;
  info.append(label, name, effect);
}

function catalogueCardStats(card, quantity = null) {
  const type = card.card_type || card.type || "Carta";
  const faith = card.faith ?? "–";
  const attack = card.strength ?? "–";
  const inspiration = card.faith ?? card.cost ?? "–";
  const crosses = card.crosses || "–";
  const copies = quantity == null ? `max ${card.max_copies}` : `${quantity} ${quantity === 1 ? "copia" : "copie"} · max ${card.max_copies}`;
  return `<span>${type}</span><span title="Fede">◈ ${faith}</span><span title="Attacco">✦ ${attack}</span><span title="Ispirazione"><i class="inspiration-symbol" aria-hidden="true"></i> ${inspiration}</span><span title="Croci">✟ ${crosses}</span><span>${copies}</span>`;
}

function adjustDeckCard(card, delta) {
  if (!ui.deckDraft) return;
  const current = ui.deckDraft.cards.get(card.name) || 0;
  const next = Math.max(0, Math.min(card.max_copies, current + delta));
  if (next) ui.deckDraft.cards.set(card.name, next);
  else ui.deckDraft.cards.delete(card.name);
  renderDeckLists();
}

function makeDeckCardRow(card, currentOnly = false) {
  const qty = ui.deckDraft.cards.get(card.name) || 0;
  const row = document.createElement("div");
  row.className = "deck-card-row";
  const main = document.createElement("div");
  main.className = "deck-card-row-main";
  main.tabIndex = 0;
  const title = document.createElement("strong");
  title.textContent = card.name;
  const meta = document.createElement("small");
  meta.className = "catalogue-card-stats";
  meta.innerHTML = catalogueCardStats(card);
  main.append(title, meta);
  main.addEventListener("mouseenter", () => showDeckCardInfo(card));
  main.addEventListener("focus", () => showDeckCardInfo(card));
  const actions = document.createElement("div");
  actions.className = "deck-row-actions";
  if (currentOnly) {
    const minus = document.createElement("button");
    minus.type = "button";
    minus.textContent = "−";
    minus.title = "Rimuovi una copia";
    minus.addEventListener("click", () => adjustDeckCard(card, -1));
    actions.append(minus);
  }
  const count = document.createElement("span");
  count.className = "deck-qty";
  count.textContent = String(qty);
  const plus = document.createElement("button");
  plus.type = "button";
  plus.textContent = "+";
  plus.title = "Aggiungi una copia";
  plus.disabled = qty >= card.max_copies;
  plus.addEventListener("click", () => adjustDeckCard(card, 1));
  actions.append(count, plus);
  row.append(main, actions);
  return row;
}

function filteredDeckCatalogue() {
  const search = $("#deck-search").value.trim().toLocaleLowerCase("it");
  const type = $("#deck-type-filter").value;
  const expansion = $("#deck-expansion-filter").value;
  return (ui.deckEditor?.cards || []).filter(card =>
    (!search || card.name.toLocaleLowerCase("it").includes(search) || (card.effect_text || "").toLocaleLowerCase("it").includes(search)) &&
    (!type || card.card_type === type) && (!expansion || card.expansion === expansion)
  );
}

function deckPayload() {
  return {
    id: ui.deckDraft.id,
    name: $("#deck-editor-name").value.trim(),
    religion: $("#deck-editor-religion").value,
    cards: [...ui.deckDraft.cards].map(([name, qty]) => ({ name, qty }))
  };
}

async function validateDeckDraft() {
  if (!ui.deckDraft) return;
  try {
    const report = await api("/api/deck-editor/validate", { cards: deckPayload().cards });
    const validity = $("#deck-validity");
    validity.textContent = report.valid ? "Deck valido" : "Da completare";
    validity.classList.toggle("valid", report.valid);
    const rules = $("#deck-rules");
    const messages = report.errors.length ? report.errors : ["Regolamento: OK"];
    if (report.notes.length) messages.push(...report.notes);
    rules.textContent = messages.join("\n");
    rules.classList.toggle("has-errors", report.errors.length > 0);
  } catch (error) {
    $("#deck-rules").textContent = error.message;
  }
}

function renderDeckLists() {
  if (!ui.deckDraft) return;
  const cardsByName = new Map((ui.deckEditor.cards || []).map(card => [card.name, card]));
  const catalogue = filteredDeckCatalogue();
  $("#deck-catalogue-count").textContent = `${catalogue.length} carte`;
  const catalogueList = $("#deck-catalogue-list");
  catalogueList.replaceChildren(...catalogue.map(card => makeDeckCardRow(card)));
  if (!catalogue.length) {
    const empty = document.createElement("div"); empty.className = "deck-empty"; empty.textContent = "Nessuna carta corrisponde ai filtri."; catalogueList.append(empty);
  }
  const selected = [...ui.deckDraft.cards.entries()].filter(([, qty]) => qty > 0).map(([name]) => cardsByName.get(name)).filter(Boolean);
  selected.sort((a, b) => a.name.localeCompare(b.name, "it"));
  const currentList = $("#deck-current-list");
  currentList.replaceChildren(...selected.map(card => makeDeckCardRow(card, true)));
  if (!selected.length) {
    const empty = document.createElement("div"); empty.className = "deck-empty"; empty.textContent = "Aggiungi carte dal catalogo."; currentList.append(empty);
  }
  const total = [...ui.deckDraft.cards.values()].reduce((sum, qty) => sum + qty, 0);
  $("#deck-total").textContent = `${total} / 45 carte`;
  clearTimeout(ui.deckValidationTimer);
  ui.deckValidationTimer = setTimeout(validateDeckDraft, 100);
}

function populateDeckEditorFilters() {
  const data = ui.deckEditor;
  const religion = $("#deck-editor-religion");
  religion.replaceChildren(...data.religions.map(value => new Option(value, value)));
  const types = [...new Set(data.cards.map(card => card.card_type))].sort((a, b) => a.localeCompare(b, "it"));
  $("#deck-type-filter").replaceChildren(new Option("Tutti i tipi", ""), ...types.map(value => new Option(value, value)));
  const expansions = [...new Set(data.cards.map(card => card.expansion).filter(Boolean))].sort((a, b) => a.localeCompare(b, "it"));
  $("#deck-expansion-filter").replaceChildren(new Option("Tutte le espansioni", ""), ...expansions.map(value => new Option(value, value)));
}

async function openDeckEditor(returnDialog) {
  ui.deckEditorReturn = returnDialog || null;
  returnDialog?.close();
  try {
    ui.deckEditor = await api("/api/deck-editor");
    ui.deckExportSelection = new Set();
    populateDeckEditorFilters();
    $("#deck-search").value = "";
    loadDeckDraft();
    $("#deck-editor-dialog").showModal();
  } catch (error) {
    setMessage(error.message, true);
    ui.deckEditorReturn?.showModal();
  }
}

$("#setup-deck-editor-button").addEventListener("click", () => openDeckEditor($("#setup-dialog")));
$("#pause-deck-editor-button").addEventListener("click", () => openDeckEditor($("#pause-dialog")));
$("#deck-new-button").addEventListener("click", () => loadDeckDraft());
$("#deck-select-all").addEventListener("change", event => {
  ui.deckExportSelection = event.target.checked
    ? new Set((ui.deckEditor?.decks || []).map(deck => deck.id))
    : new Set();
  renderDeckLibrary();
});
$("#deck-import-button").addEventListener("click", () => $("#deck-import-input").click());
$("#deck-import-input").addEventListener("change", async event => {
  const files = [...event.target.files];
  event.target.value = "";
  if (!files.length) return;
  const button = $("#deck-import-button");
  button.disabled = true;
  try {
    const documents = [];
    const parseErrors = [];
    for (const file of files) {
      try {
        documents.push(JSON.parse(await file.text()));
      } catch (_) {
        parseErrors.push(`${file.name}: il file non contiene JSON valido.`);
      }
    }
    if (!documents.length) throw new Error(parseErrors.join(" | "));
    const result = await api("/api/deck-editor/import", { documents });
    ui.deckEditor = result.editor;
    ui.config = result.config;
    ui.deckExportSelection = new Set((result.report.imported || []).map(deck => deck.id));
    refreshDeckSelects(result.config);
    populateDeckEditorFilters();
    const lastImported = (result.report.imported || []).at(-1);
    loadDeckDraft(lastImported ? result.editor.decks.find(deck => deck.id === lastImported.id) : null);
    const importErrors = [...(result.report.errors || []), ...parseErrors];
    const details = importErrors.length ? ` ${importErrors.join(" | ")}` : "";
    setMessage(result.message + details, importErrors.length > 0);
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
});
$("#deck-export-button").addEventListener("click", async () => {
  const button = $("#deck-export-button");
  button.disabled = true;
  try {
    const result = await api("/api/deck-editor/export", { deck_ids: [...ui.deckExportSelection] });
    const content = JSON.stringify(result.document, null, 2);
    if (window.pywebview?.api?.save_deck_export) {
      const saved = await window.pywebview.api.save_deck_export(content, result.filename);
      if (saved?.cancelled) return;
      if (!saved?.ok) throw new Error(saved?.message || "Esportazione non riuscita.");
      setMessage(`Deck esportati in ${saved.path}`);
    } else {
      const blob = new Blob([content], { type: "application/json;charset=utf-8" });
      const link = document.createElement("a");
      const downloadUrl = URL.createObjectURL(blob);
      link.href = downloadUrl;
      link.download = result.filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
      setMessage("Esportazione deck completata.");
    }
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    updateDeckExportControls();
  }
});
$("#deck-search").addEventListener("input", renderDeckLists);
$("#deck-type-filter").addEventListener("change", renderDeckLists);
$("#deck-expansion-filter").addEventListener("change", renderDeckLists);
$("#deck-editor-name").addEventListener("input", () => { if (ui.deckDraft) ui.deckDraft.name = $("#deck-editor-name").value; });
$("#deck-editor-religion").addEventListener("change", () => { if (ui.deckDraft) ui.deckDraft.religion = $("#deck-editor-religion").value; });
$("#deck-save-button").addEventListener("click", async () => {
  const button = $("#deck-save-button");
  button.disabled = true;
  try {
    const result = await api("/api/deck-editor/save", deckPayload());
    ui.deckEditor = result.editor;
    ui.config = result.config;
    if (!result.config.decks.some(deck => deck.id === ui.options?.default_deck)) {
      ui.options.default_deck = result.config.defaults.player_deck;
    }
    refreshDeckSelects(result.config);
    populateDeckEditorFilters();
    loadDeckDraft(result.editor.decks.find(deck => deck.id === result.deck.id));
    setMessage(result.message);
  } catch (error) {
    setMessage(error.message, true);
    $("#deck-rules").textContent = error.message;
    $("#deck-rules").classList.add("has-errors");
  } finally {
    button.disabled = false;
  }
});
$("#deck-delete-button").addEventListener("click", async () => {
  if (!ui.deckDraft?.id || !window.confirm(`Eliminare definitivamente “${ui.deckDraft.name}”?`)) return;
  try {
    const result = await api("/api/deck-editor/delete", { id: ui.deckDraft.id });
    ui.deckEditor = result.editor;
    ui.config = result.config;
    if (!result.config.decks.some(deck => deck.id === ui.options?.default_deck)) {
      ui.options.default_deck = result.config.defaults.player_deck;
    }
    refreshDeckSelects(result.config);
    populateDeckEditorFilters();
    loadDeckDraft();
    setMessage(result.message);
  } catch (error) { setMessage(error.message, true); }
});
$("#deck-editor-dialog").addEventListener("close", () => {
  const returnDialog = ui.deckEditorReturn;
  ui.deckEditorReturn = null;
  if (returnDialog && !$("dialog[open]")) returnDialog.showModal();
});

const testZoneDefinitions = [
  { key: "deck", label: "Reliquiario", collection: true, gridClass: "resource-zone" },
  { key: "hand", label: "Mano", collection: true, gridClass: "resource-zone" },
  { key: "graveyard", label: "Cimitero", collection: true, gridClass: "resource-zone" },
  { key: "excommunicated", label: "Scomunicate", collection: true, gridClass: "resource-zone" },
  { key: "attack", label: "Santi in attacco", slots: 3, types: ["santo", "token"], gridClass: "saint-zone" },
  { key: "defense", label: "Santi in difesa", slots: 3, types: ["santo", "token"], gridClass: "saint-zone" },
  { key: "artifacts", label: "Artefatti", slots: 4, types: ["artefatto"], gridClass: "artifact-zone" },
  { key: "building", label: "Edificio", slots: 1, types: ["edificio"], gridClass: "single-zone" },
  { key: "innate", label: "Carta Innata", slots: 1, types: ["innata"], gridClass: "single-zone" }
];

function emptyTestPlayer(name) {
  return {
    name, deck: [], hand: [], graveyard: [], excommunicated: [],
    attack: [null, null, null], defense: [null, null, null],
    artifacts: [null, null, null, null], building: [null], innate: [null], sin: 0
  };
}

function resetTestDraft() {
  ui.testDraft = { players: [emptyTestPlayer("Pellegrino"), emptyTestPlayer("Custode")] };
  ui.testStep = 0;
}

function testCurrentPlayerIndex() { return ui.testStep === 0 ? 1 : 0; }

function testCardByName(name) {
  return ui.testEditor?.cards.find(card => card.name === name) || null;
}

function testPlayerCounts(player) {
  const counts = new Map();
  [player.deck, player.hand, player.graveyard, player.excommunicated, player.attack, player.defense, player.artifacts, player.building, player.innate]
    .flat().filter(Boolean).forEach(name => counts.set(name, (counts.get(name) || 0) + 1));
  return counts;
}

function testZoneDescription(player, zone, slot = null) {
  const values = player[zone];
  if (slot != null) return values[slot] || "Slot vuoto";
  if (!values.length) return "Zona vuota";
  const counts = new Map();
  values.forEach(name => counts.set(name, (counts.get(name) || 0) + 1));
  return [...counts].map(([name, qty]) => `${qty}× ${name}`).join(", ");
}

function renderTestBoard() {
  const playerIndex = testCurrentPlayerIndex();
  const player = ui.testDraft.players[playerIndex];
  $("#test-game-title").textContent = playerIndex === 1 ? "Configura l'avversario" : "Configura il giocatore";
  const board = $("#test-zone-board");
  board.replaceChildren(...testZoneDefinitions.map(definition => {
    const group = document.createElement("section");
    group.className = `test-zone-group ${definition.gridClass || ""}`;
    const heading = document.createElement("h3");
    heading.textContent = definition.label;
    const slots = document.createElement("div");
    slots.className = "test-zone-slots";
    const count = definition.collection ? 1 : definition.slots;
    for (let slot = 0; slot < count; slot += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "test-zone-button";
      const description = testZoneDescription(player, definition.key, definition.collection ? null : slot);
      const filled = definition.collection ? player[definition.key].length > 0 : Boolean(player[definition.key][slot]);
      button.classList.toggle("filled", filled);
      const title = document.createElement("strong");
      title.textContent = definition.collection ? `${player[definition.key].length} carte` : `${definition.label} ${slot + 1}`;
      const detail = document.createElement("small");
      detail.textContent = description;
      button.append(title, detail);
      const open = event => { event.preventDefault(); openTestPicker(playerIndex, definition, definition.collection ? null : slot); };
      button.addEventListener("click", open);
      button.addEventListener("contextmenu", open);
      slots.append(button);
    }
    group.append(heading, slots);
    return group;
  }));
}

function renderTestWizard() {
  $$('[data-test-step]').forEach(node => node.classList.toggle("active", Number(node.dataset.testStep) === ui.testStep));
  $("#test-zone-step").hidden = ui.testStep === 2;
  $("#test-start-step").hidden = ui.testStep !== 2;
  $("#test-back-button").disabled = ui.testStep === 0;
  $("#test-next-button").hidden = ui.testStep === 2;
  $("#test-start-button").hidden = ui.testStep !== 2;
  if (ui.testStep < 2) renderTestBoard();
  else {
    $("#test-game-title").textContent = "Scegli il primo turno";
    const summaries = ui.testDraft.players.map((player, index) => {
      const field = [...player.attack, ...player.defense, ...player.artifacts, ...player.building].filter(Boolean).length;
      const innate = player.innate.filter(Boolean).length;
      return `${index === 0 ? "Giocatore" : "Avversario"}: ${player.deck.length} deck, ${player.hand.length} mano, ${player.graveyard.length} cimitero, ${player.excommunicated.length} scomunicate, ${field} terreno, ${innate} Innata.`;
    });
    $("#test-scenario-summary").textContent = summaries.join(" ");
  }
}

function showTestPickerPreview(card) {
  const preview = $("#test-picker-preview");
  preview.replaceChildren();
  const type = document.createElement("small");
  type.textContent = `${card.card_type} · ${card.expansion || "Neutre"} · ${card.crosses || "–"} Croci`;
  const name = document.createElement("strong");
  name.textContent = card.name;
  const effect = document.createElement("p");
  effect.textContent = `${card.strength != null ? `ATK ${card.strength} · Fede ${card.faith ?? "–"} · ` : ""}${card.effect_text || "Nessun testo effetto."}`;
  preview.append(type, name, effect);
}

function testPickerCards() {
  const definition = ui.testPicker.definition;
  const search = $("#test-card-search").value.trim().toLocaleLowerCase("it");
  const type = $("#test-card-type").value;
  const expansion = $("#test-card-expansion").value;
  return ui.testEditor.cards.filter(card => {
    const cardType = card.card_type.toLocaleLowerCase("it");
    return (!definition.types || definition.types.includes(cardType)) &&
      (!type || card.card_type === type) && (!expansion || card.expansion === expansion) &&
      (!search || card.name.toLocaleLowerCase("it").includes(search) || (card.effect_text || "").toLocaleLowerCase("it").includes(search));
  });
}

function adjustTestZone(card, delta) {
  const { playerIndex, definition, slot } = ui.testPicker;
  const player = ui.testDraft.players[playerIndex];
  if (definition.collection) {
    if (delta > 0) {
      const used = testPlayerCounts(player).get(card.name) || 0;
      if (used >= card.max_copies) { setMessage(`${card.name}: massimo ${card.max_copies} copie.`, true); return; }
      player[definition.key].push(card.name);
    } else {
      const index = player[definition.key].lastIndexOf(card.name);
      if (index >= 0) player[definition.key].splice(index, 1);
    }
  } else if (delta > 0) {
    const old = player[definition.key][slot];
    const used = (testPlayerCounts(player).get(card.name) || 0) - (old === card.name ? 1 : 0);
    if (used >= card.max_copies) { setMessage(`${card.name}: massimo ${card.max_copies} copie.`, true); return; }
    player[definition.key][slot] = card.name;
  } else {
    player[definition.key][slot] = null;
  }
  renderTestPicker();
}

function testCardRow(card) {
  const row = document.createElement("div");
  row.className = "deck-card-row test-card-add-row";
  row.tabIndex = 0;
  row.setAttribute("role", "button");
  row.setAttribute("aria-label", `Aggiungi ${card.name} alla zona`);
  const main = document.createElement("div");
  main.className = "deck-card-row-main";
  const title = document.createElement("strong"); title.textContent = card.name;
  const meta = document.createElement("small"); meta.className = "catalogue-card-stats"; meta.innerHTML = catalogueCardStats(card);
  main.append(title, meta);
  main.addEventListener("mouseenter", () => showTestPickerPreview(card));
  row.addEventListener("focus", () => showTestPickerPreview(card));
  row.addEventListener("click", () => adjustTestZone(card, 1));
  row.addEventListener("keydown", event => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    adjustTestZone(card, 1);
  });
  row.append(main);
  return row;
}

function renderTestPickerSelection() {
  const { playerIndex, definition, slot } = ui.testPicker;
  const player = ui.testDraft.players[playerIndex];
  const names = definition.collection ? player[definition.key] : [player[definition.key][slot]].filter(Boolean);
  const counts = new Map(); names.forEach(name => counts.set(name, (counts.get(name) || 0) + 1));
  const list = $("#test-zone-selection");
  list.replaceChildren(...[...counts].map(([name, qty]) => {
    const card = testCardByName(name);
    const row = document.createElement("div"); row.className = "deck-card-row";
    const main = document.createElement("div"); main.className = "deck-card-row-main";
    const title = document.createElement("strong"); title.textContent = name;
    const meta = document.createElement("small"); meta.className = "catalogue-card-stats";
    meta.innerHTML = card ? catalogueCardStats(card, qty) : `${qty} ${qty === 1 ? "copia" : "copie"}`;
    main.append(title, meta);
    main.addEventListener("mouseenter", () => card && showTestPickerPreview(card));
    const actions = document.createElement("div"); actions.className = "deck-row-actions";
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "−"; remove.addEventListener("click", () => adjustTestZone(card, -1));
    actions.append(remove); row.append(main, actions); return row;
  }));
  if (!names.length) { const empty = document.createElement("div"); empty.className = "deck-empty"; empty.textContent = "Zona vuota."; list.append(empty); }
}

function renderTestPicker() {
  const results = $("#test-card-results");
  const cards = testPickerCards();
  results.replaceChildren(...cards.map(testCardRow));
  if (!cards.length) { const empty = document.createElement("div"); empty.className = "deck-empty"; empty.textContent = "Nessuna carta disponibile con questi filtri."; results.append(empty); }
  renderTestPickerSelection();
}

function openTestPicker(playerIndex, definition, slot) {
  ui.testPicker = { playerIndex, definition, slot };
  $("#test-picker-side").textContent = playerIndex === 1 ? "AVVERSARIO" : "GIOCATORE";
  $("#test-picker-title").textContent = slot == null ? definition.label : `${definition.label} ${slot + 1}`;
  $("#test-card-search").value = "";
  $("#test-card-type").value = "";
  $("#test-card-expansion").value = "";
  renderTestPicker();
  $("#test-card-picker-dialog").showModal();
}

async function openTestGame() {
  $("#setup-dialog").close();
  $("#main-menu-dialog").close();
  ui.testStarted = false;
  try {
    ui.testEditor = await api("/api/test-editor");
    resetTestDraft();
    const types = [...new Set(ui.testEditor.cards.map(card => card.card_type))].sort((a, b) => a.localeCompare(b, "it"));
    const expansions = [...new Set(ui.testEditor.cards.map(card => card.expansion).filter(Boolean))].sort((a, b) => a.localeCompare(b, "it"));
    $("#test-card-type").replaceChildren(new Option("Tutti i tipi", ""), ...types.map(value => new Option(value, value)));
    $("#test-card-expansion").replaceChildren(new Option("Tutte le espansioni", ""), ...expansions.map(value => new Option(value, value)));
    renderTestWizard();
    $("#test-game-dialog").showModal();
  } catch (error) { setMessage(error.message, true); $("#main-menu-dialog").showModal(); }
}

$("#setup-test-game-button").addEventListener("click", openTestGame);
$("#test-card-search").addEventListener("input", renderTestPicker);
$("#test-card-type").addEventListener("change", renderTestPicker);
$("#test-card-expansion").addEventListener("change", renderTestPicker);
$("#test-picker-close").addEventListener("click", () => $("#test-card-picker-dialog").close());
$("#test-picker-continue").addEventListener("click", () => { $("#test-card-picker-dialog").close(); renderTestBoard(); });
$("#test-next-button").addEventListener("click", () => { ui.testStep = Math.min(2, ui.testStep + 1); renderTestWizard(); });
$("#test-back-button").addEventListener("click", () => { ui.testStep = Math.max(0, ui.testStep - 1); renderTestWizard(); });
$("#test-start-button").addEventListener("click", async () => {
  const button = $("#test-start-button"); button.disabled = true;
  try {
    const active = Number($('input[name="test-active-player"]:checked').value);
    const data = await api("/api/test-game", {
      mode: $("#test-game-mode").value,
      active_player: active,
      initial_draw: $("#test-initial-draw").checked,
      players: ui.testDraft.players
    });
    ui.selectedUid = null;
    showGameScreen();
    render(data);
    ui.testStarted = true;
    $("#test-game-dialog").close();
    setMessage(data.message);
  } catch (error) { setMessage(error.message, true); }
  finally { button.disabled = false; }
});
$("#test-game-dialog").addEventListener("close", () => {
  if (!ui.testStarted && !$("dialog[open]")) $("#main-menu-dialog").showModal();
});

function updateSetupMode() {
  const mode = $("#game-mode").value;
  const versusAi = mode === "ai";
  $("#opponent-name").disabled = versusAi;
  $("#opponent-name").value = versusAi ? "Custode" : ($("#opponent-name").value === "Custode" ? "Giocatore 2" : $("#opponent-name").value);
  $("#opponent-name-label").textContent = versusAi ? "Nome CPU" : "Nome giocatore 2";
  $("#opponent-setup").hidden = false;
  $("#online-setup").hidden = true;
  $("#start-game-button").hidden = false;
}

function onlineProfile() {
  return {
    player_name: ui.options?.username || $("#player-name").value,
    player_deck: preferredDeckId() || $("#player-deck").value,
    chain_enabled: ui.options?.chain_enabled !== false
  };
}

function openMainMenu() {
  clearTimeout(ui.onlineTimer);
  hideGameScreen();
  if (!$("dialog[open]")) $("#main-menu-dialog").showModal();
}

function renderRoom(status) {
  const previousPhase = ui.onlinePhase;
  ui.onlinePhase = status.phase;
  $("#online-room-title").textContent = status.room_name || "Stanza Holy War";
  $("#room-status").textContent = status.message || "In attesa...";
  const participants = status.participants || [];
  const named = role => participants.find(player => player.role === role);
  const p1 = named("player1");
  const p2 = named("player2");
  const spectators = participants.filter(player => player.role === "spectator");
  $("#role-player1").textContent = p1?.name || "Libero";
  $("#role-player2").textContent = p2?.name || "Libero";
  $("#role-spectator").textContent = `${spectators.length} / 5${spectators.length ? ` · ${spectators.map(p => p.name).join(", ")}` : ""}`;
  $$('[data-room-role]').forEach(button => button.classList.toggle("selected", button.dataset.roomRole === status.player_role));
  const choosingDeck = status.phase === "deck_select" && ["player1", "player2"].includes(status.player_role);
  $("#online-deck-choice").hidden = !choosingDeck;
  if (choosingDeck && previousPhase !== "deck_select") {
    $("#online-player-deck").value = preferredDeckId() || ui.config.defaults.player_deck;
  }
  $("#proceed-room").hidden = !(status.is_host && status.phase === "waiting");
  const playersReady = [p1, p2].every(player => player?.ready);
  $("#start-online-match").hidden = !(status.is_host && status.phase === "deck_select");
  $("#start-online-match").disabled = !playersReady;
  if (!status.playing && status.connected && !$("#online-room-dialog").open) {
    $("#online-browser-dialog").close();
    $("#online-room-dialog").showModal();
  }
}

async function pollOnline() {
  clearTimeout(ui.onlineTimer);
  if (ui.onlineBusy) {
    ui.onlineTimer = setTimeout(pollOnline, 500);
    return;
  }
  ui.onlineBusy = true;
  try {
    const status = await api("/api/multiplayer/status");
    if (status.phase === "rejected" || status.phase === "return_browser") {
      const message = status.message;
      if ($("#rematch-dialog").open) $("#rematch-dialog").close();
      if ($("#surrender-dialog").open) $("#surrender-dialog").close();
      await api("/api/multiplayer/leave", {});
      hideGameScreen();
      if ($("#online-room-dialog").open) $("#online-room-dialog").close();
      if (!$("#online-browser-dialog").open) $("#online-browser-dialog").showModal();
      $("#browser-status").textContent = message;
      await refreshRooms();
      return;
    }
    renderRoom(status);
    if (status.playing) {
      if ($("#online-room-dialog").open) $("#online-room-dialog").close();
      const data = await api("/api/state");
      const key = JSON.stringify(data.game);
      if (key !== ui.onlineStateKey) {
        ui.onlineStateKey = key;
        showGameScreen();
        render(data);
      }
      if (status.rematch_required && status.rematch_vote == null && !$("#rematch-dialog").open) {
        $("#rematch-dialog").showModal();
      } else if ((!status.rematch_required || status.rematch_vote != null) && $("#rematch-dialog").open) {
        $("#rematch-dialog").close();
      }
    }
    if (status.connected) ui.onlineTimer = setTimeout(pollOnline, 650);
  } catch (error) {
    $("#online-status").textContent = error.message;
    ui.onlineTimer = setTimeout(pollOnline, 1500);
  } finally {
    ui.onlineBusy = false;
  }
}

async function refreshRooms() {
  clearTimeout(ui.browserTimer);
  if (!$("#online-browser-dialog").open || ui.browserBusy) return;
  ui.browserBusy = true;
  $("#browser-status").textContent = "Ricerca delle stanze...";
  try {
    const data = await api("/api/multiplayer/find", onlineProfile());
    const rooms = data.rooms || [];
    $("#browser-status").textContent = `${rooms.length} ${rooms.length === 1 ? "stanza trovata" : "stanze trovate"}.`;
    const list = $("#room-list");
    if (!rooms.length) {
      list.innerHTML = '<div class="empty-room-list">Nessuna partita aperta. Puoi essere il primo host.</div>';
      return;
    }
    list.replaceChildren(...rooms.map(room => {
      const row = document.createElement("article");
      row.className = "room-entry";
      const players = (room.playerNames || []).join(", ") || "In attesa";
      row.innerHTML = `<div><strong>${room.passwordProtected ? "🔒 " : ""}${room.roomName}</strong><br><small>${room.members}/${room.maxMembers} partecipanti</small></div><span>${players}</span><span class="room-phase">${room.phase === "started" ? "Avviata" : "In attesa"}</span>`;
      const join = document.createElement("button");
      join.className = "button button-primary"; join.type = "button"; join.textContent = "Entra";
      join.addEventListener("click", () => beginJoinRoom(room));
      row.append(join);
      return row;
    }));
  } catch (error) {
    $("#browser-status").textContent = error.message;
  } finally {
    ui.browserBusy = false;
    if ($("#online-browser-dialog").open) ui.browserTimer = setTimeout(refreshRooms, 5000);
  }
}

async function joinSelectedRoom(password = "") {
  const room = ui.joinTarget;
  if (!room) return;
  try {
    const status = await api("/api/multiplayer/join", { ...onlineProfile(), lobby_id: room.lobbyId, room_name: room.roomName, password_protected: room.passwordProtected, password });
    if ($("#join-password-dialog").open) $("#join-password-dialog").close();
    renderRoom(status); pollOnline();
  } catch (error) { setMessage(error.message, true); }
}

function beginJoinRoom(room) {
  clearTimeout(ui.browserTimer);
  ui.joinTarget = room;
  if (room.passwordProtected) { $("#join-room-password").value = ""; $("#join-password-dialog").showModal(); }
  else joinSelectedRoom();
}

async function leaveOnlineRoom() {
  await api("/api/multiplayer/leave", {});
  hideGameScreen();
  clearTimeout(ui.onlineTimer);
  ui.onlineStateKey = null;
  ui.onlinePhase = null;
  if ($("#online-room-dialog").open) $("#online-room-dialog").close();
  if (!$("#online-browser-dialog").open) $("#online-browser-dialog").showModal();
  refreshRooms();
}

$("#refresh-rooms").addEventListener("click", refreshRooms);
$("#open-host-room").addEventListener("click", () => { $("#room-name").value = `${ui.options.username} - Holy War`; $("#room-password").value = ""; $("#host-room-dialog").showModal(); });
$("#cancel-host-room").addEventListener("click", () => $("#host-room-dialog").close());
$("#host-room-form").addEventListener("submit", async event => {
  event.preventDefault();
  clearTimeout(ui.browserTimer);
  try {
    const status = await api("/api/multiplayer/host", { ...onlineProfile(), room_name: $("#room-name").value, password: $("#room-password").value });
    $("#host-room-dialog").close(); renderRoom(status); pollOnline();
  } catch (error) { setMessage(error.message, true); }
});
$("#join-password-form").addEventListener("submit", event => { event.preventDefault(); joinSelectedRoom($("#join-room-password").value); });
$("#cancel-join-room").addEventListener("click", () => $("#join-password-dialog").close());
async function performRoomAction(payload) {
  try {
    await api("/api/multiplayer/room-action", payload);
    renderRoom(await api("/api/multiplayer/status"));
  } catch (error) { setMessage(error.message, true); }
}
$$('[data-room-role]').forEach(button => button.addEventListener("click", () => performRoomAction({ action: "select_role", role: button.dataset.roomRole })));
$("#proceed-room").addEventListener("click", () => performRoomAction({ action: "proceed" }));
$("#confirm-online-deck").addEventListener("click", () => performRoomAction({ action: "select_deck", deck: $("#online-player-deck").value }));
$("#start-online-match").addEventListener("click", () => performRoomAction({ action: "start" }));
$("#leave-room").addEventListener("click", leaveOnlineRoom);

$("#game-mode").addEventListener("change", updateSetupMode);
$("#setup-back-menu").addEventListener("click", () => { $("#setup-dialog").close(); openMainMenu(); });
$("#setup-form").addEventListener("submit", async event => {
  event.preventDefault();
  if ($("#game-mode").value === "online") return;
  const submit = $("#start-game-button");
  submit.disabled = true;
  try {
    const data = await api("/api/new-game", {
      mode: $("#game-mode").value,
      player_name: $("#player-name").value,
      opponent_name: $("#opponent-name").value,
      player_deck: $("#player-deck").value,
      opponent_deck: $("#opponent-deck").value,
      chain_enabled: ui.options?.chain_enabled !== false
    });
    ui.selectedUid = null;
    showGameScreen();
    render(data);
    $("#setup-dialog").close();
    setMessage(data.message);
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    submit.disabled = false;
  }
});

const helpDialog = $("#help-dialog");
const pauseDialog = $("#pause-dialog");
const surrenderDialog = $("#surrender-dialog");
function openPause() {
  if ($('dialog[open]')) return;
  const online = ui.state?.mode === "online";
  ["#new-game-button", "#pause-help-button", "#pause-log-button", "#bug-report-button"]
    .forEach(selector => $(selector).hidden = false);
  $("#pause-deck-editor-button").hidden = online;
  $("#resume-button").textContent = online ? "Annulla" : "Riprendi partita";
  pauseDialog.showModal();
}
$("#menu-button").addEventListener("click", openPause);
$("#resume-button").addEventListener("click", () => pauseDialog.close());
$("#pause-help-button").addEventListener("click", () => { pauseDialog.close(); helpDialog.showModal(); });
$("#pause-log-button").addEventListener("click", () => { pauseDialog.close(); $("#match-log").focus(); });
function openBugReport() {
  window.open("https://forms.gle/c195nMKhR8WKRpP87", "_blank", "noopener,noreferrer");
}
$("#bug-report-button").addEventListener("click", openBugReport);
$("#menu-bug-report").addEventListener("click", openBugReport);
$("#online-browser-bug-report").addEventListener("click", openBugReport);
$("#surrender-button").addEventListener("click", () => surrenderDialog.showModal());
$("#pause-surrender-button").addEventListener("click", () => { pauseDialog.close(); surrenderDialog.showModal(); });
$("#confirm-surrender-button").addEventListener("click", () => { surrenderDialog.close(); sendAction({ type: "surrender" }); });

function openMatchSetup(mode) {
  $("#main-menu-dialog").close();
  $("#game-mode").value = mode;
  $("#player-name").value = ui.options.username;
  $("#player-deck").value = preferredDeckId();
  updateSetupMode();
  $("#setup-dialog").showModal();
}
$("#menu-single-player").addEventListener("click", () => openMatchSetup("ai"));
$("#menu-local-multiplayer").addEventListener("click", () => openMatchSetup("local"));
$("#menu-online-multiplayer").addEventListener("click", () => {
  $("#main-menu-dialog").close(); $("#online-browser-dialog").showModal(); refreshRooms();
});
$("#online-browser-back").addEventListener("click", () => {
  clearTimeout(ui.browserTimer);
  $("#online-browser-dialog").close();
  openMainMenu();
});
$("#menu-deck-editor").addEventListener("click", () => openDeckEditor($("#main-menu-dialog")));
$("#menu-test-field").addEventListener("click", openTestGame);
function openOptions(returnTo = "main") {
  ui.optionsReturnTo = returnTo;
  if ($("#main-menu-dialog").open) $("#main-menu-dialog").close();
  if ($("#online-browser-dialog").open) $("#online-browser-dialog").close();
  $("#option-username").value = ui.options.username;
  $("#option-default-deck").value = preferredDeckId();
  $("#option-default-chain").value = ui.options.chain_enabled === false ? "off" : "on";
  $("#options-dialog").showModal();
}
function closeOptions() {
  $("#options-dialog").close();
  if (ui.optionsReturnTo === "online") {
    $("#online-browser-dialog").showModal();
    refreshRooms();
  } else {
    openMainMenu();
  }
}
$("#menu-options").addEventListener("click", () => openOptions("main"));
$("#online-browser-options").addEventListener("click", () => openOptions("online"));
$("#cancel-options").addEventListener("click", closeOptions);
$("#options-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    ui.options = await api("/api/options", {
      username: $("#option-username").value,
      default_deck: $("#option-default-deck").value,
      chain_enabled: $("#option-default-chain").value === "on"
    });
    setMessage(ui.options.message);
    closeOptions();
  } catch (error) { setMessage(error.message, true); }
});
$("#menu-close").addEventListener("click", () => $("#close-game-dialog").showModal());
$("#confirm-close-game").addEventListener("click", async () => {
  try { await window.pywebview?.api?.close(); } catch (_) { window.close(); }
});
async function voteRematch(accept) {
  $("#rematch-dialog").close();
  try { await api("/api/multiplayer/room-action", { action: "rematch", accept }); pollOnline(); }
  catch (error) { setMessage(error.message, true); }
}
$("#accept-rematch").addEventListener("click", () => voteRematch(true));
$("#decline-rematch").addEventListener("click", () => voteRematch(false));
$("#confirm-coin-toss").addEventListener("click", () => sendAction({ type: "confirm_coin_toss" }));
$("#coin-toss-dialog").addEventListener("cancel", event => event.preventDefault());
$("#main-menu-dialog").addEventListener("cancel", event => event.preventDefault());
$("#rematch-dialog").addEventListener("cancel", event => event.preventDefault());
$("#online-browser-dialog").addEventListener("cancel", event => {
  event.preventDefault();
  $("#online-browser-back").click();
});
$("#online-room-dialog").addEventListener("cancel", event => {
  event.preventDefault();
  leaveOnlineRoom();
});
$("#setup-dialog").addEventListener("cancel", event => {
  event.preventDefault();
  $("#setup-back-menu").click();
});
$("#options-dialog").addEventListener("cancel", event => {
  event.preventDefault();
  $("#cancel-options").click();
});
$("#close-inspector").addEventListener("click", () => $(".inspector").classList.remove("open"));
$$('[data-close-dialog]').forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if (ui.placement) { event.preventDefault(); clearInteractionState(); return; }
  if (ui.targeting) { event.preventDefault(); cancelTargeting(); return; }
  if (!$("#card-context-menu").hidden) { event.preventDefault(); $("#card-context-menu").hidden = true; return; }
  if (!$('dialog[open]')) { event.preventDefault(); openPause(); }
});

async function boot() {
  try {
    const [config, data, online, options] = await Promise.all([
      api("/api/config"), api("/api/state"), api("/api/multiplayer/status"), api("/api/options")
    ]);
    ui.config = config;
    ui.options = options;
    if (!config.decks.some(deck => deck.id === ui.options.default_deck)) {
      ui.options.default_deck = config.defaults.player_deck;
    }
    refreshDeckSelects(config);
    $("#player-name").value = options.username;
    $("#player-deck").value = ui.options.default_deck;
    $("#online-player-deck").value = ui.options.default_deck;
    $("#option-default-deck").value = ui.options.default_deck;
    $("#option-default-chain").value = options.chain_enabled === false ? "off" : "on";
    updateSetupMode();
    if (data.game) {
      render(data);
      const first = data.game.players[0].hand[0];
      if (first) showCard(first, $(`[data-uid="${CSS.escape(first.uid)}"]`));
    } else {
      hideGameScreen();
    }
    if (online.connected) { renderRoom(online); pollOnline(); }
    else $("#main-menu-dialog").showModal();
  } catch (error) {
    setMessage("Avvia l'interfaccia con: python -m holywar.web", true);
    $("#end-turn-button").disabled = true;
  }
}

boot();
