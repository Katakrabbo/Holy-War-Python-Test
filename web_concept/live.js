const ui = {
  state: null,
  selectedUid: null,
  drag: null,
  placement: null,
  targeting: null,
  contextCard: null,
  effectSelection: null,
  aiTimer: null,
  decisionId: null,
  runtimeSelectionOrder: [],
  deckEditor: null,
  deckDraft: null,
  deckEditorReturn: null,
  deckValidationTimer: null
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

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
  if (card.strength != null) stats.push(`<span>Forza <b>${card.strength}</b></span>`);
  if (card.faith != null) stats.push(`<span>Fede <b>${card.faith}</b></span>`);
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
  button.innerHTML = `<small>${card.type.toUpperCase()} · ✟ ${card.cost ?? "–"}</small><strong>${card.name}</strong>${stats}`;
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
  const cards = Array.from({ length: enemy.hand_count }, () => {
    const back = document.createElement("article");
    back.className = "card card-back";
    back.setAttribute("aria-label", "Carta avversaria coperta");
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
  ui.state = data.game;
  const player = ui.state.players[0];
  const enemy = ui.state.players[1];
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
    `<span title="Ispirazione richiesta">✟ Ispirazione <b>${card.cost ?? "–"}</b></span>`,
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
    `<span title="Ispirazione">✟ ${option.card.cost ?? "–"}</span>`,
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
        kind: "play", uid: card.uid, placement: options.placement, formatter: options.formatter
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
  if (selection.action.formatter === "monsone") {
    target = `monsone:discard=${values[0]?.value || ""};return=${values[1]?.value || ""}`;
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
$("#new-game-button").addEventListener("click", () => {
  $("#pause-dialog").close();
  $("#setup-dialog").showModal();
});

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
  (ui.deckEditor?.decks || []).forEach(deck => {
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
    list.append(button);
  });
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
  meta.textContent = `${card.card_type} · ${card.crosses || "–"} Croci · max ${card.max_copies}`;
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

function updateSetupMode() {
  const versusAi = $("#game-mode").value === "ai";
  $("#opponent-name").disabled = versusAi;
  $("#opponent-name").value = versusAi ? "Custode" : ($("#opponent-name").value === "Custode" ? "Giocatore 2" : $("#opponent-name").value);
  $("#opponent-name-label").textContent = versusAi ? "Nome CPU" : "Nome giocatore 2";
}

$("#game-mode").addEventListener("change", updateSetupMode);
$("#setup-form").addEventListener("submit", async event => {
  event.preventDefault();
  const submit = $("#start-game-button");
  submit.disabled = true;
  try {
    const data = await api("/api/new-game", {
      mode: $("#game-mode").value,
      player_name: $("#player-name").value,
      opponent_name: $("#opponent-name").value,
      player_deck: $("#player-deck").value,
      opponent_deck: $("#opponent-deck").value
    });
    ui.selectedUid = null;
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
function openPause() { if (!$('dialog[open]')) pauseDialog.showModal(); }
$("#menu-button").addEventListener("click", openPause);
$("#resume-button").addEventListener("click", () => pauseDialog.close());
$("#pause-help-button").addEventListener("click", () => { pauseDialog.close(); helpDialog.showModal(); });
$("#pause-log-button").addEventListener("click", () => { pauseDialog.close(); $("#match-log").focus(); });
$("#surrender-button").addEventListener("click", () => surrenderDialog.showModal());
$("#pause-surrender-button").addEventListener("click", () => { pauseDialog.close(); surrenderDialog.showModal(); });
$("#confirm-surrender-button").addEventListener("click", () => { surrenderDialog.close(); sendAction({ type: "surrender" }); });
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
    const [config, data] = await Promise.all([api("/api/config"), api("/api/state")]);
    refreshDeckSelects(config);
    updateSetupMode();
    render(data);
    const first = data.game.players[0].hand[0];
    if (first) showCard(first, $(`[data-uid="${CSS.escape(first.uid)}"]`));
    $("#setup-dialog").showModal();
  } catch (error) {
    setMessage("Avvia l'interfaccia con: python -m holywar.web", true);
    $("#end-turn-button").disabled = true;
  }
}

boot();
