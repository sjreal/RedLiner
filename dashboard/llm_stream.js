/* Shared LLM loading overlay and SSE token stream. */
(function () {
  let activeController = null;

  function el(id) {
    return document.getElementById(id);
  }

  function overlay() {
    return el("llm-loading-overlay");
  }

  function show(options = {}) {
    const box = overlay();
    if (!box) return;
    box.hidden = false;
    box.dataset.state = options.state || "loading";
    const title = el("llm-loading-title");
    const status = el("llm-loading-status");
    const stream = el("llm-loading-stream");
    const cancel = el("llm-loading-cancel");
    if (title) title.textContent = options.title || "Drafting counter-proposal…";
    if (status) status.textContent = options.status || "Waiting for the model's first token…";
    if (stream) {
      stream.textContent = "";
      stream.classList.remove("error");
    }
    if (cancel) cancel.hidden = options.cancelable === false;
  }

  function hide() {
    const box = overlay();
    if (box) box.hidden = true;
    activeController = null;
  }

  function setStatus(text) {
    const status = el("llm-loading-status");
    if (status) status.textContent = text;
  }

  function append(text) {
    const stream = el("llm-loading-stream");
    if (!stream || !text) return;
    stream.textContent += text;
    stream.scrollTop = stream.scrollHeight;
  }

  function setInlineStatus(id, text) {
    if (!id) return;
    const target = el(id);
    if (target) target.textContent = text;
  }

  function fail(message) {
    const status = el("llm-loading-status");
    const stream = el("llm-loading-stream");
    const cancel = el("llm-loading-cancel");
    if (status) status.textContent = `Error: ${message}`;
    if (stream) stream.classList.add("error");
    if (cancel) cancel.hidden = false;
    const box = overlay();
    if (box) box.dataset.state = "error";
  }

  function cancel() {
    if (activeController) {
      activeController.abort();
      activeController = null;
    }
    hide();
  }

  function parseFrame(frame) {
    let event = "message";
    const data = [];
    for (const rawLine of frame.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith(":")) continue;
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        data.push(line.slice(5).trim());
      }
    }
    if (!data.length) return null;
    const payload = data.join("\n");
    try {
      return { event, data: JSON.parse(payload) };
    } catch (err) {
      return { event, data: { text: payload } };
    }
  }

  async function streamDraft({ dealId, instructions = "", statusEl, onToken, onDone, onError }) {
    if (!dealId) {
      const error = new Error("Select a deal first.");
      if (onError) onError(error);
      return "";
    }

    show({
      title: "Drafting counter-proposal…",
      status: "Waiting for the model's first token…",
    });
    setInlineStatus(statusEl, "Waiting for the model…");

    const controller = new AbortController();
    activeController = controller;
    let buffer = "";
    let full = "";
    let firstToken = true;

    try {
      const response = await fetch("/api/email/draft-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deal_id: dealId, instructions }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text().catch(() => "");
        let detail = text;
        try {
          const parsed = JSON.parse(text);
          detail = parsed.detail || parsed.message || text;
        } catch (err) {
          // Keep the raw response text.
        }
        throw new Error(detail || `HTTP ${response.status}`);
      }
      if (!response.body) {
        throw new Error("Streaming is not supported by this browser.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const message = parseFrame(frame);
          if (!message) continue;

          if (message.event === "status") {
            setStatus("Thinking…");
          } else if (message.event === "token") {
            const token = message.data.text || "";
            full += token;
            setStatus("Streaming draft…");
            append(token);
            if (firstToken) {
              firstToken = false;
              hide();
              setInlineStatus(statusEl, "Streaming…");
            }
            if (onToken) onToken(token, full);
          } else if (message.event === "done") {
            full = message.data.text || full;
            setInlineStatus(statusEl, "");
            if (onDone) onDone(full);
            hide();
            return full;
          } else if (message.event === "error") {
            throw new Error(message.data.error || "Streaming failed.");
          }
        }
      }

      if (full) {
        setInlineStatus(statusEl, "");
        if (onDone) onDone(full);
        hide();
        return full;
      }
      throw new Error("The model returned no text.");
    } catch (err) {
      if (err.name === "AbortError") {
        setInlineStatus(statusEl, "");
        hide();
        return "";
      }
      if (firstToken) {
        fail(err.message || "Streaming failed.");
      } else {
        setInlineStatus(statusEl, `Draft failed: ${err.message}`);
      }
      if (onError) onError(err);
      return "";
    } finally {
      if (activeController === controller) activeController = null;
    }
  }

  function bindCancel() {
    const button = el("llm-loading-cancel");
    if (button) button.addEventListener("click", cancel);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindCancel);
  } else {
    bindCancel();
  }

  window.RedLinerLLM = {
    show,
    hide,
    setStatus,
    append,
    fail,
    cancel,
    streamDraft,
    isActive: () => Boolean(activeController),
  };
})();
