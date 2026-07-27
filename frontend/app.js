"use strict";

// Endereço principal da RAG API. Altere apenas esta constante ao trocar host ou porta.
const API_URL = "http://localhost:8003/pergunta";
const HEALTH_URL = API_URL.replace(/\/pergunta\/?$/, "/health");
const DEFAULT_TOP_K = 5;

const elements = {
  form: document.querySelector("#questionForm"),
  input: document.querySelector("#questionInput"),
  sendButton: document.querySelector("#sendButton"),
  messages: document.querySelector("#chatMessages"),
  welcome: document.querySelector("#welcomeState"),
  counter: document.querySelector("#messageCounter"),
  systemStatus: document.querySelector("#systemStatus"),
  modelStatus: document.querySelector("#modelStatus"),
  newConversationButton: document.querySelector("#newConversationButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  suggestions: document.querySelectorAll(".suggestion"),
};

const state = {
  messageCount: 0,
  isLoading: false,
  loadingElement: null,
};

function formatTime(date = new Date()) {
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function updateMessageCounter() {
  const suffix = state.messageCount === 1 ? "mensagem" : "mensagens";
  elements.counter.textContent = `${state.messageCount} ${suffix}`;
}

function setStatus(element, modifier, label, title) {
  element.className = `status-pill status-pill--${modifier}`;
  element.querySelector(".status-label").textContent = label;
  element.title = title;
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  });
}

function hideWelcomeState() {
  if (elements.welcome) {
    elements.welcome.hidden = true;
  }
}

function createAvatar(role) {
  const avatar = document.createElement("div");
  avatar.className = "message__avatar";

  if (role === "assistant") {
    const image = document.createElement("img");
    image.src = "assets/logo.png";
    image.alt = "Assistente";
    avatar.append(image);
  } else {
    avatar.textContent = "Você";
    avatar.setAttribute("aria-label", "Você");
  }

  return avatar;
}

function normalizeUrl(value) {
  if (!value) return null;

  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function createSources(sources) {
  if (!Array.isArray(sources) || sources.length === 0) return null;

  const section = document.createElement("section");
  section.className = "sources";
  section.setAttribute("aria-label", "Fontes utilizadas");

  const heading = document.createElement("div");
  heading.className = "sources__heading";
  heading.append(document.createTextNode("Fontes utilizadas"));

  const count = document.createElement("span");
  count.className = "sources__count";
  count.textContent = `${sources.length} ${sources.length === 1 ? "fonte" : "fontes"}`;
  heading.append(count);
  section.append(heading);

  sources.forEach((source, index) => {
    const safeUrl = normalizeUrl(source.url);
    const card = document.createElement(safeUrl ? "a" : "article");
    card.className = "source-card";

    if (safeUrl) {
      card.href = safeUrl;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
      card.title = "Abrir notícia em uma nova aba";
    }

    const title = document.createElement("h3");
    title.className = "source-card__title";

    const titleText = document.createElement("span");
    titleText.textContent = source.titulo || `Fonte ${index + 1}`;
    title.append(titleText);

    if (safeUrl) {
      const arrow = document.createElement("span");
      arrow.className = "source-card__arrow";
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "↗";
      title.append(arrow);
    }

    const excerpt = document.createElement("p");
    excerpt.className = "source-card__excerpt";
    excerpt.textContent = source.texto || "Trecho não disponibilizado pela API.";

    card.append(title, excerpt);

    if (typeof source.score === "number") {
      const score = document.createElement("span");
      score.className = "source-card__score";
      score.textContent = `Relevância: ${source.score.toFixed(4)}`;
      card.append(score);
    }

    if (safeUrl) {
      const visibleUrl = document.createElement("span");
      visibleUrl.className = "source-card__url";
      visibleUrl.textContent = safeUrl;
      card.append(visibleUrl);
    }

    section.append(card);
  });

  return section;
}

function addMessage(role, text, options = {}) {
  hideWelcomeState();

  const article = document.createElement("article");
  article.className = `message message--${role}`;
  if (options.isError) article.classList.add("message--error");

  const content = document.createElement("div");
  content.className = "message__content";

  const bubble = document.createElement("div");
  bubble.className = "message__bubble";

  const paragraph = document.createElement("p");
  paragraph.className = "message__text";
  paragraph.textContent = text;
  bubble.append(paragraph);

  const sources = createSources(options.sources);
  if (sources) bubble.append(sources);

  const meta = document.createElement("div");
  meta.className = "message__meta";
  meta.textContent = formatTime();

  content.append(bubble, meta);
  if (role === "user") {
    article.append(content, createAvatar(role));
  } else {
    article.append(createAvatar(role), content);
  }

  elements.messages.append(article);

  if (options.count !== false) {
    state.messageCount += 1;
    updateMessageCounter();
  }

  scrollToLatest();
  return article;
}

function showLoadingMessage() {
  hideWelcomeState();

  const article = document.createElement("article");
  article.className = "message message--assistant";
  article.setAttribute("aria-label", "Consultando as notícias do recorte");

  const content = document.createElement("div");
  content.className = "message__content";

  const bubble = document.createElement("div");
  bubble.className = "message__bubble";

  const loading = document.createElement("div");
  loading.className = "loading-content";
  loading.append(document.createTextNode("Consultando as notícias do recorte..."));

  const dots = document.createElement("span");
  dots.className = "loading-dots";
  dots.setAttribute("aria-hidden", "true");
  dots.innerHTML = "<i></i><i></i><i></i>";
  loading.append(dots);

  bubble.append(loading);
  content.append(bubble);
  article.append(createAvatar("assistant"), content);
  elements.messages.append(article);

  state.loadingElement = article;
  scrollToLatest();
}

function removeLoadingMessage() {
  state.loadingElement?.remove();
  state.loadingElement = null;
}

function setLoading(isLoading) {
  state.isLoading = isLoading;
  elements.input.disabled = isLoading;
  elements.sendButton.disabled = isLoading;
  elements.sendButton.setAttribute("aria-busy", String(isLoading));

  if (isLoading) {
    showLoadingMessage();
  } else {
    removeLoadingMessage();
    elements.input.focus();
  }
}

function friendlyError(error) {
  if (error instanceof TypeError) {
    return "Servidor indisponível. Confirme se a RAG API está ativa e acessível pelo navegador.";
  }

  return error.message || "Erro ao consultar a API. Tente novamente em alguns instantes.";
}

async function parseErrorResponse(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // A API pode retornar uma resposta sem JSON em falhas de infraestrutura.
  }

  if (response.status === 503) return "Servidor indisponível. Tente novamente em alguns instantes.";
  return `Erro ao consultar a API (HTTP ${response.status}).`;
}

async function askQuestion(question) {
  addMessage("user", question);
  setLoading(true);

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pergunta: question, top_k: DEFAULT_TOP_K }),
    });

    if (!response.ok) {
      throw new Error(await parseErrorResponse(response));
    }

    const data = await response.json();
    if (typeof data.resposta !== "string") {
      throw new Error("A API retornou uma resposta em formato inesperado.");
    }

    setLoading(false);
    addMessage("assistant", data.resposta, { sources: data.fontes || [] });
    setStatus(elements.systemStatus, "online", "Sistema online", "A RAG API respondeu com sucesso");
    if (data.ollama_skipped === false) {
      setStatus(elements.modelStatus, "served", "Modelo servido", "O Ollama gerou a resposta com sucesso");
    } else {
      setStatus(
        elements.modelStatus,
        "neutral",
        "Serviço não verificado",
        "O Evidence Check respondeu sem chamar o Ollama"
      );
    }
  } catch (error) {
    setLoading(false);
    addMessage("assistant", friendlyError(error), { isError: true });
    setStatus(elements.modelStatus, "error", "Modelo indisponível", "Não foi possível obter uma resposta");
  }
}

function submitCurrentQuestion() {
  const question = elements.input.value.trim();
  if (state.isLoading || !question) return;

  if (question.length < 3) {
    addMessage("assistant", "Digite uma pergunta com pelo menos 3 caracteres.", { isError: true });
    return;
  }

  elements.input.value = "";
  resizeInput();
  askQuestion(question);
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 180)}px`;
}

function resetConversation(askConfirmation = false) {
  if (state.isLoading) return;
  if (askConfirmation && state.messageCount > 0 && !window.confirm("Deseja limpar todas as mensagens desta conversa?")) {
    return;
  }

  elements.messages.querySelectorAll(".message").forEach((message) => message.remove());
  state.messageCount = 0;
  updateMessageCounter();
  elements.welcome.hidden = false;
  elements.input.value = "";
  resizeInput();
  elements.input.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function checkSystemHealth() {
  setStatus(elements.systemStatus, "checking", "Verificando sistema", "Consultando o endpoint de health");

  try {
    const response = await fetch(HEALTH_URL, { method: "GET" });
    if (!response.ok) throw new Error("Health check indisponível");

    const data = await response.json();
    if (data.status !== "ok") throw new Error("Status inesperado");
    setStatus(elements.systemStatus, "online", "Sistema online", "RAG API disponível");
  } catch {
    setStatus(elements.systemStatus, "offline", "Sistema offline", "A RAG API não respondeu ao health check");
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitCurrentQuestion();
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitCurrentQuestion();
  }
});

elements.input.addEventListener("input", resizeInput);
elements.newConversationButton.addEventListener("click", () => resetConversation(false));
elements.clearChatButton.addEventListener("click", () => resetConversation(true));

elements.suggestions.forEach((button) => {
  button.addEventListener("click", () => {
    elements.input.value = button.textContent.trim();
    resizeInput();
    submitCurrentQuestion();
  });
});

updateMessageCounter();
checkSystemHealth();
window.setInterval(checkSystemHealth, 60_000);
