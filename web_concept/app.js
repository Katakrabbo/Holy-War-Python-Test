const cards = {
  arca: {
    name: "Arca della salvezza",
    type: "Maledizione",
    cost: 8,
    effect: "Scegli due Santi sul campo. Distruggi tutti gli altri Santi.",
    help: "Scegli due Santi da proteggere, poi conferma l'azione.",
    theme: "curse",
    action: "Gioca carta"
  },
  acqua: {
    name: "Acqua",
    type: "Artefatto",
    cost: 2,
    effect: "Finché questa carta è presente sul terreno, i tuoi Santi sono immuni agli effetti delle Maledizioni.",
    help: "Puoi collocare questa carta in uno slot Artefatto libero.",
    theme: "artifact",
    action: "Gioca artefatto"
  },
  altare: {
    name: "Altare dei Sette Sigilli",
    type: "Edificio",
    cost: 7,
    effect: "Accumula Segnalini Sigillo quando un tuo Santo viene distrutto o giochi una carta Sigillo.",
    help: "Carta avversaria: puoi leggerne l'effetto, ma non controllarla.",
    theme: "building",
    action: "Carta avversaria",
    disabled: true
  },
  araldo: {
    name: "Araldo della Fine",
    type: "Santo",
    cost: 6,
    strength: 4,
    faith: 5,
    effect: "Ottiene +5 Forza quando l'Altare dei Sette Sigilli possiede almeno 7 Segnalini Sigillo.",
    help: "Un Santo può essere evocato in uno degli slot verdi liberi.",
    theme: "saint",
    action: "Evoca Santo"
  },
  "enemy-araldo": {
    name: "Araldo della Fine",
    type: "Santo avversario · Attacco",
    cost: 6,
    strength: 4,
    faith: 5,
    effect: "Ottiene +5 Forza quando l'Altare dei Sette Sigilli possiede almeno 7 Segnalini Sigillo.",
    help: "È nella prima linea avversaria e può essere scelto come bersaglio di un attacco.",
    theme: "saint",
    action: "Seleziona bersaglio",
    disabled: true
  },
  guardiano: {
    name: "Guardiano dello Yin",
    type: "Santo",
    cost: 4,
    strength: 3,
    faith: 6,
    effect: "Protegge gli equilibri dello Yin finché rimane sul campo.",
    help: "Santo avversario: selezionalo come bersaglio durante un attacco.",
    theme: "saint",
    action: "Seleziona bersaglio",
    disabled: true
  },
  "enemy-guardiano": {
    name: "Guardiano dello Yin",
    type: "Santo avversario · Difesa",
    cost: 4,
    strength: 3,
    faith: 6,
    effect: "Occupa la seconda linea dietro Araldo della Fine.",
    help: "Se Araldo della Fine lascia il campo, questo Santo avanza immediatamente nello slot Attacco davanti a sé.",
    theme: "saint",
    action: "Seconda linea",
    disabled: true
  },
  custode: {
    name: "Custode dei Sigilli",
    type: "Santo avversario · Attacco",
    cost: 4,
    strength: 3,
    faith: 6,
    effect: "Santo avversario schierato nella prima linea.",
    help: "Può essere scelto come bersaglio di un attacco.",
    theme: "saint",
    action: "Seleziona bersaglio",
    disabled: true
  },
  guerriero: {
    name: "Guerriero Santificato",
    type: "Santo",
    cost: 4,
    strength: 5,
    faith: 4,
    effect: "Santo schierato nel tuo campo e pronto a ricevere comandi.",
    help: "Puoi attaccare, attivare un'abilità o consultare i suoi modificatori.",
    theme: "saint",
    action: "Mostra azioni"
  },
  "own-araldo": {
    name: "Araldo della Fine",
    type: "Santo · Attacco",
    cost: 6,
    strength: 4,
    faith: 5,
    effect: "Ottiene +5 Forza quando l'Altare dei Sette Sigilli possiede almeno 7 Segnalini Sigillo.",
    help: "È nella tua prima linea: può attaccare oppure attivare le proprie abilità valide.",
    theme: "saint",
    action: "Mostra azioni"
  },
  "own-guardiano": {
    name: "Guardiano dello Yin",
    type: "Santo · Difesa",
    cost: 4,
    strength: 3,
    faith: 6,
    effect: "Occupa la seconda linea dietro Guerriero Santificato.",
    help: "Se il Santo davanti lascia il campo, avanzerà automaticamente nello slot Attacco della stessa colonna.",
    theme: "saint",
    action: "Mostra azioni"
  },
  reliquia: {
    name: "Reliquia Solare",
    type: "Artefatto",
    cost: 3,
    effect: "Artefatto dimostrativo usato soltanto nel concept grafico.",
    help: "Le azioni disponibili dipenderanno sempre dal motore Python.",
    theme: "artifact",
    action: "Mostra azioni"
  },
  cura: {
    name: "Cura Rapida",
    type: "Benedizione",
    cost: 3,
    effect: "Ripristina Fede a un Santo scelto.",
    help: "Dopo aver premuto Gioca, il campo evidenzierà soltanto i bersagli validi.",
    theme: "blessing",
    action: "Gioca benedizione"
  },
  foresta: {
    name: "Foresta Sacra",
    type: "Edificio",
    cost: 5,
    effect: "Edificio che supporta i Santi legati alla natura.",
    help: "Puoi avere un solo Edificio: uno nuovo sostituirà quello presente.",
    theme: "building",
    action: "Gioca edificio"
  }
};

// Adatta soltanto i nomi lunghi delle carte schierate: dimensioni e soglie
// restano una responsabilità visiva del frontend, non del motore di gioco.
function fitCardName(label) {
  const length = Array.from(label.textContent.trim()).length;
  if (length >= 24) {
    label.classList.add("name-very-long");
  } else if (length >= 18) {
    label.classList.add("name-long");
  }
}

document.querySelectorAll(".unit-row .game-card strong").forEach(fitCardName);

const preview = document.querySelector("#card-preview");
const previewName = document.querySelector("#preview-name");
const previewType = document.querySelector("#preview-type");
const previewStats = document.querySelector("#preview-stats");
const previewEffect = document.querySelector("#preview-effect");
const eventMessage = document.querySelector("#event-message");
const inspector = document.querySelector(".inspector");
const board = document.querySelector(".board");
const inspirationGauge = document.querySelector("#inspiration-gauge");
const inspirationValue = document.querySelector("#inspiration-value");
const inspirationOwner = document.querySelector("#inspiration-owner");
let selectedElement = document.querySelector(".hand-card.selected");
let selectedCard = "arca";

function setActiveInspiration(owner, value) {
  inspirationOwner.textContent = owner;
  inspirationValue.textContent = String(value);
  inspirationGauge.style.setProperty("--value", String(value * 10));
  inspirationGauge.setAttribute("aria-valuenow", String(value));
}

function selectCard(element) {
  const card = cards[element.dataset.card];
  if (!card) return;

  document.querySelectorAll(".game-card.selected, .mini-card.selected").forEach(item => item.classList.remove("selected"));
  element.classList.add("selected");
  selectedElement = element;
  selectedCard = element.dataset.card;

  preview.className = `card-preview ${card.theme}`;
  previewName.textContent = card.name;
  previewType.textContent = card.type.toUpperCase();
  previewEffect.textContent = card.effect;
  previewStats.innerHTML = `<span>Costo <b>${card.cost}</b></span>${card.strength ? `<span>Forza <b>${card.strength}</b></span><span>Fede <b>${card.faith}</b></span>` : ""}`;
  board.classList.remove("selection-cancelled");
  inspector.classList.add("open");
  eventMessage.innerHTML = `<strong>${card.name}</strong> selezionata. Il pannello mostra effetto e azioni disponibili.`;
}

function bindCardElement(element) {
  if (element.dataset.uiBound === "true") return;
  element.dataset.uiBound = "true";
  element.addEventListener("click", () => selectCard(element));
}

document.querySelectorAll("[data-card]").forEach(bindCardElement);

function appendLog(message) {
  const list = document.querySelector("#match-log .game-log");
  const item = document.createElement("li");
  item.innerHTML = `<time>Adesso</time>${message}`;
  list.prepend(item);
  eventMessage.textContent = item.textContent;
}

const activationRules = {
  arca: { count: 2, selector: ".unit-row .game-card", prompt: "Scegli due Santi da preservare" },
  cura: { count: 1, selector: ".player-attack-line .game-card, .player-defense-line .game-card", prompt: "Scegli un tuo Santo" },
  reliquia: { count: 1, selector: ".player-attack-line .game-card, .player-defense-line .game-card", prompt: "Scegli il Santo che riceve l'effetto" },
  "own-guardiano": { count: 1, selector: ".enemy-attack-line .game-card", prompt: "Scegli un Santo avversario" },
  foresta: { count: 1, selector: ".player-attack-line .game-card, .player-defense-line .game-card", prompt: "Scegli un tuo Santo" }
};

function refreshActivatableCards() {
  document.querySelectorAll("[data-card]").forEach(element => {
    element.classList.toggle("effect-ready", Boolean(activationRules[element.dataset.card]));
  });
}

function cardName(element) {
  return cards[element?.dataset.card]?.name || element?.querySelector("strong, span")?.textContent?.trim() || "Carta";
}

let dragState = null;

function clearDragState() {
  document.querySelectorAll(".drop-valid, .drop-hover, .attack-target").forEach(element => {
    element.classList.remove("drop-valid", "drop-hover", "attack-target");
  });
  dragState?.source?.classList.remove("dragging");
  dragState = null;
}

function placementTargetsFor(card) {
  const type = card.type.toLowerCase();
  if (type.includes("santo")) return ".player-attack-line .empty-slot.unit, .player-defense-line .empty-slot.unit";
  if (type.includes("artefatto")) return ".own-support .empty-slot:not(.building-slot)";
  if (type.includes("edificio")) return ".own-support .building-slot.empty-slot";
  return "";
}

function configureDraggableCards() {
  document.querySelectorAll(".hand-card[data-card]").forEach(element => {
    const card = cards[element.dataset.card];
    element.draggable = Boolean(placementTargetsFor(card));
  });
  document.querySelectorAll(".player-attack-line .game-card[data-card], .player-defense-line .game-card[data-can-attack-from-defense='true']").forEach(element => {
    element.draggable = true;
    element.dataset.attackDrag = "true";
  });
}

document.addEventListener("dragstart", event => {
  const source = event.target.closest("[data-card]");
  if (!source) return;

  if (source.matches(".hand-card")) {
    const selector = placementTargetsFor(cards[source.dataset.card]);
    if (!selector) {
      event.preventDefault();
      return;
    }
    const targets = [...document.querySelectorAll(selector)];
    if (!targets.length) {
      event.preventDefault();
      appendLog(`<b>${cardName(source)}</b>: nessuno slot compatibile libero.`);
      return;
    }
    dragState = { kind: "placement", source, targets };
    targets.forEach(target => target.classList.add("drop-valid"));
  } else if (source.dataset.attackDrag === "true") {
    const targets = [...document.querySelectorAll(".enemy-attack-line .game-card[data-card]")];
    if (!targets.length) {
      event.preventDefault();
      return;
    }
    dragState = { kind: "attack", source, targets };
    targets.forEach(target => target.classList.add("drop-valid", "attack-target"));
  } else {
    event.preventDefault();
    return;
  }

  source.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", source.dataset.card);
});

document.addEventListener("dragover", event => {
  const target = event.target.closest(".drop-valid");
  if (!target || !dragState?.targets.includes(target)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  target.classList.add("drop-hover");
});

document.addEventListener("dragleave", event => {
  event.target.closest(".drop-valid")?.classList.remove("drop-hover");
});

function deployCard(source, target) {
  const key = source.dataset.card;
  const card = cards[key];
  const isSaint = card.type.toLowerCase().includes("santo");
  const isBuilding = card.type.toLowerCase().includes("edificio");

  target.classList.remove("empty-slot", "valid-target", "drop-valid", "drop-hover", "unit", "building-slot");
  target.classList.add("deployed-card");
  if (isSaint) target.classList.add("game-card", "saint", "own-card");
  else target.classList.add("mini-card", isBuilding ? "building" : "artifact");
  target.dataset.card = key;
  target.tabIndex = 0;
  target.setAttribute("role", "button");
  target.innerHTML = isSaint
    ? `<strong>${card.name}</strong><span class="stats">✦ ${card.strength ?? "–"}&nbsp;&nbsp; ◈ ${card.faith ?? "–"}</span>`
    : `<span>${card.name}</span>`;

  const deployedName = target.querySelector("strong");
  if (deployedName) fitCardName(deployedName);

  appendLog(`Hai posizionato <b>${card.name}</b> sul terreno.`);
  source.remove();
  const handCards = document.querySelectorAll(".hand-card");
  document.querySelector(".hand-cards").style.setProperty("--hand-count", String(Math.max(1, handCards.length)));
  bindCardElement(target);
  selectCard(target);
  refreshActivatableCards();
  configureDraggableCards();
}

document.addEventListener("drop", event => {
  const target = event.target.closest(".drop-valid");
  if (!target || !dragState?.targets.includes(target)) return;
  event.preventDefault();
  if (dragState.kind === "placement") {
    deployCard(dragState.source, target);
  } else {
    appendLog(`<b>${cardName(dragState.source)}</b> dichiara un attacco contro <b>${cardName(target)}</b>.`);
  }
  clearDragState();
});

document.addEventListener("dragend", clearDragState);

const contextMenu = document.querySelector("#card-context-menu");
let contextSource = null;

document.addEventListener("contextmenu", event => {
  const source = event.target.closest("[data-card].effect-ready");
  if (!source) return;
  event.preventDefault();
  contextSource = source;
  document.querySelector("#context-card-name").textContent = cardName(source);
  contextMenu.hidden = false;
  const left = Math.min(event.clientX, window.innerWidth - 205);
  const top = Math.min(event.clientY, window.innerHeight - 115);
  contextMenu.style.left = `${Math.max(8, left)}px`;
  contextMenu.style.top = `${Math.max(8, top)}px`;
});

document.addEventListener("pointerdown", event => {
  if (!event.target.closest("#card-context-menu")) contextMenu.hidden = true;
});

document.querySelector("#inspect-card-button").addEventListener("click", () => {
  if (contextSource) selectCard(contextSource);
  contextMenu.hidden = true;
});

const targetingToolbar = document.querySelector("#targeting-toolbar");
const targetingTitle = document.querySelector("#targeting-title");
const targetingCount = document.querySelector("#targeting-count");
const confirmTargetsButton = document.querySelector("#confirm-targets-button");
let targetingState = null;

function updateTargetingUI() {
  if (!targetingState) return;
  const selected = targetingState.selected.size;
  targetingCount.textContent = `${selected}/${targetingState.rule.count}`;
  confirmTargetsButton.disabled = selected !== targetingState.rule.count;
}

function cancelTargeting() {
  document.querySelectorAll(".effect-target, .target-selected").forEach(element => element.classList.remove("effect-target", "target-selected"));
  targetingToolbar.hidden = true;
  targetingState = null;
}

function startTargeting(source) {
  const rule = activationRules[source.dataset.card];
  if (!rule) return;
  const candidates = [...document.querySelectorAll(rule.selector)].filter(element => element !== source);
  if (!candidates.length) {
    appendLog(`<b>${cardName(source)}</b>: nessun bersaglio valido.`);
    return;
  }
  cancelTargeting();
  targetingState = { source, rule, candidates, selected: new Set() };
  candidates.forEach(element => element.classList.add("effect-target"));
  targetingTitle.textContent = rule.prompt;
  targetingToolbar.hidden = false;
  updateTargetingUI();
}

document.querySelector("#activate-effect-button").addEventListener("click", () => {
  contextMenu.hidden = true;
  if (contextSource) startTargeting(contextSource);
});

document.addEventListener("click", event => {
  if (!targetingState) return;
  const target = event.target.closest(".effect-target");
  if (!target || !targetingState.candidates.includes(target)) return;
  event.preventDefault();
  event.stopPropagation();
  if (targetingState.selected.has(target)) {
    targetingState.selected.delete(target);
    target.classList.remove("target-selected");
  } else {
    if (targetingState.selected.size >= targetingState.rule.count) {
      const first = targetingState.selected.values().next().value;
      targetingState.selected.delete(first);
      first.classList.remove("target-selected");
    }
    targetingState.selected.add(target);
    target.classList.add("target-selected");
  }
  updateTargetingUI();
}, true);

confirmTargetsButton.addEventListener("click", () => {
  if (!targetingState || targetingState.selected.size !== targetingState.rule.count) return;
  const source = targetingState.source;
  const targets = [...targetingState.selected].map(cardName).join(", ");
  appendLog(`<b>${cardName(source)}</b> attiva il proprio effetto su <b>${targets}</b>.`);
  if (source.matches(".hand-card")) {
    source.remove();
    const count = document.querySelectorAll(".hand-card").length;
    document.querySelector(".hand-cards").style.setProperty("--hand-count", String(Math.max(1, count)));
  }
  cancelTargeting();
});

document.querySelector("#cancel-targets-button").addEventListener("click", cancelTargeting);
refreshActivatableCards();
configureDraggableCards();

document.querySelector("#end-turn-button").addEventListener("click", event => {
  const label = document.querySelector("#turn-label");
  const phase = document.querySelector("#phase-label");
  const isPlayer = label.textContent === "Il tuo turno";
  label.textContent = isPlayer ? "Turno avversario" : "Il tuo turno";
  phase.textContent = isPlayer ? "L'avversario sta valutando la mossa" : "Fase principale · Turno 5";
  event.currentTarget.textContent = isPlayer ? "Attendi…" : "Termina turno";
  event.currentTarget.disabled = isPlayer;
  setActiveInspiration(isPlayer ? "Custode" : "Pellegrino", isPlayer ? 4 : 10);
  eventMessage.innerHTML = isPlayer
    ? "<strong>Custode</strong> sta giocando. I tuoi comandi sono temporaneamente disabilitati."
    : "<strong>Nuovo turno.</strong> Hai ottenuto Ispirazione e pescato una carta.";
  if (isPlayer) {
    window.setTimeout(() => {
      label.textContent = "Il tuo turno";
      phase.textContent = "Fase principale · Turno 5";
      event.currentTarget.textContent = "Termina turno";
      event.currentTarget.disabled = false;
      setActiveInspiration("Pellegrino", 10);
      eventMessage.innerHTML = "<strong>Nuovo turno.</strong> Hai ottenuto Ispirazione e pescato una carta.";
    }, 1400);
  }
});

document.querySelector("#close-inspector").addEventListener("click", () => inspector.classList.remove("open"));

const helpDialog = document.querySelector("#help-dialog");
const pauseDialog = document.querySelector("#pause-dialog");
const surrenderDialog = document.querySelector("#surrender-dialog");
const zoneDialog = document.querySelector("#zone-dialog");
const matchLog = document.querySelector("#match-log");

const zoneContents = {
  "opponent:graveyard": [
    { name: "Pellegrino Caduto", type: "Santo", cost: 3, strength: 2, faith: 4, effect: "Quando viene distrutto, il suo controllore recupera 1 Ispirazione." },
    { name: "Sigillo Spezzato", type: "Maledizione", cost: 4, effect: "Riduce temporaneamente la Fede del Santo scelto." },
    { name: "Lama del Custode", type: "Artefatto", cost: 2, effect: "Il Santo equipaggiato ottiene Forza aggiuntiva durante il proprio attacco." },
    { name: "Preghiera Infranta", type: "Benedizione", cost: 3, effect: "Previene una parte del prossimo danno subito dal giocatore." },
    { name: "Messaggero del Vespro", type: "Santo", cost: 5, strength: 4, faith: 3, effect: "Quando entra in campo, permette di osservare una carta della mano avversaria." },
    { name: "Cripta dei Giusti", type: "Edificio", cost: 6, effect: "Potenzia gli effetti attivati dalle carte presenti nel Cimitero." }
  ],
  "opponent:excommunicated": [
    { name: "Martire Senza Nome", type: "Santo", cost: 4, strength: 3, faith: 5, effect: "Non può lasciare la zona delle carte scomunicate tramite effetti comuni." }
  ],
  "player:graveyard": [
    { name: "Araldo della Fine", type: "Santo", cost: 6, strength: 4, faith: 5, effect: cards.araldo.effect },
    { name: "Acqua Benedetta", type: "Artefatto", cost: 2, effect: cards.acqua.effect },
    { name: "Cura Rapida", type: "Benedizione", cost: 3, effect: cards.cura.effect }
  ],
  "player:excommunicated": []
};

function showZoneCardDetail(card, activeButton) {
  document.querySelectorAll(".zone-card-entry.active").forEach(button => button.classList.remove("active"));
  activeButton?.classList.add("active");
  document.querySelector("#zone-preview-type").textContent = card.type.toUpperCase();
  document.querySelector("#zone-preview-name").textContent = card.name;
  document.querySelector("#zone-preview-effect").textContent = card.effect;
  const stats = document.querySelector("#zone-preview-stats");
  stats.innerHTML = `<span>Costo <b>${card.cost ?? "–"}</b></span>${card.strength != null ? `<span>Forza <b>${card.strength}</b></span><span>Fede <b>${card.faith}</b></span>` : ""}`;
}

function openZoneDialog(zone) {
  // Quando il motore segnala che questa zona sostituisce il Deck, il suo
  // contenuto resta nascosto esattamente come quello di un normale mazzo.
  if (zone.dataset.deckReplacement === "true") return;

  const owner = zone.dataset.zoneOwner;
  const kind = zone.dataset.zoneKind;
  const contents = zoneContents[`${owner}:${kind}`] || [];
  const title = kind === "graveyard" ? "Cimitero" : "Carte scomunicate";
  document.querySelector("#zone-dialog-owner").textContent = owner === "player" ? "LE TUE CARTE" : "CARTE AVVERSARIE";
  document.querySelector("#zone-dialog-title").textContent = title;
  document.querySelector("#zone-dialog-summary").textContent = `${contents.length} ${contents.length === 1 ? "carta" : "carte"} in questa zona.`;
  const list = document.querySelector("#zone-card-list");
  const detail = document.querySelector("#zone-card-detail");
  list.replaceChildren();

  if (!contents.length) {
    detail.hidden = true;
    const empty = document.createElement("li");
    empty.className = "empty-zone-message";
    empty.textContent = "Questa zona è vuota.";
    list.append(empty);
  } else {
    detail.hidden = false;
    contents.forEach((card, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      const cardNameLabel = document.createElement("strong");
      const cardTypeLabel = document.createElement("small");
      item.style.setProperty("--stack-index", String(index + 1));
      button.className = "zone-card-entry";
      button.type = "button";
      cardNameLabel.textContent = card.name;
      cardTypeLabel.textContent = card.type;
      button.append(cardTypeLabel, cardNameLabel);
      button.addEventListener("mouseenter", () => showZoneCardDetail(card, button));
      button.addEventListener("focus", () => showZoneCardDetail(card, button));
      button.addEventListener("click", () => showZoneCardDetail(card, button));
      item.append(button);
      list.append(item);
    });
    showZoneCardDetail(contents[0], list.querySelector(".zone-card-entry"));
  }

  zoneDialog.showModal();
}

document.querySelectorAll(".inspectable-zone").forEach(zone => {
  const locked = zone.dataset.deckReplacement === "true";
  zone.classList.toggle("zone-locked", locked);
  zone.setAttribute("aria-disabled", String(locked));
  zone.addEventListener("click", () => openZoneDialog(zone));
});

function openPauseMenu() {
  if (!document.querySelector("dialog[open]")) pauseDialog.showModal();
}

document.querySelector("#menu-button").addEventListener("click", openPauseMenu);
document.querySelector("#resume-button").addEventListener("click", () => pauseDialog.close());
document.querySelector("#pause-help-button").addEventListener("click", () => {
  pauseDialog.close();
  helpDialog.showModal();
});
document.querySelector("#pause-log-button").addEventListener("click", () => {
  pauseDialog.close();
  matchLog.focus();
  matchLog.classList.add("log-pulse");
  window.setTimeout(() => matchLog.classList.remove("log-pulse"), 700);
});
document.querySelector("#surrender-button").addEventListener("click", () => surrenderDialog.showModal());
document.querySelector("#pause-surrender-button").addEventListener("click", () => {
  pauseDialog.close();
  surrenderDialog.showModal();
});
document.querySelector("#confirm-surrender-button").addEventListener("click", () => {
  surrenderDialog.close();
  eventMessage.innerHTML = "<strong>Concept:</strong> la conferma della resa verrà collegata al controller di partita.";
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  if (targetingState) {
    event.preventDefault();
    cancelTargeting();
    return;
  }
  if (!contextMenu.hidden) {
    event.preventDefault();
    contextMenu.hidden = true;
    return;
  }
  if (document.querySelector("dialog[open]")) return;
  event.preventDefault();
  openPauseMenu();
});
document.querySelectorAll("[data-close-dialog]").forEach(button => {
  button.addEventListener("click", () => button.closest("dialog").close());
});
