"use strict";

const historyListEl = document.getElementById("history-list");
const emptyMessageEl = document.getElementById("empty-message");
const refreshBtn = document.getElementById("refresh-btn");
const clearBtn = document.getElementById("clear-btn");
const statusTextEl = document.getElementById("status-text");

const POLL_INTERVAL_MS = 1500;

// 編集中(未保存)のXMLテキストを保持する。ここに入っている間は、
// 定期更新(ポーリング)で上書きされないようにする。
const editingXml = new Map(); // id -> テキスト

function formatTimestamp(unixSeconds) {
  const d = new Date(unixSeconds * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function isEditingXmlNow() {
  const active = document.activeElement;
  return !!(active && active.classList && active.classList.contains("fm-block__editor"));
}

async function fetchHistory({ force = false } = {}) {
  // XMLテキストエリアを編集中は、自動更新で再描画するとカーソル位置が
  // リセットされてしまうため、自動更新(ポーリング)はスキップする。
  // 「今すぐ更新」ボタンなど明示的な操作(force)の場合は必ず更新する。
  if (!force && isEditingXmlNow()) {
    return;
  }
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    renderHistory(data.items || []);
    statusTextEl.textContent = `最終更新: ${new Date().toLocaleTimeString("ja-JP")}`;
  } catch (e) {
    statusTextEl.textContent = "サーバーに接続できません。server.py が起動しているか確認してください。";
  }
}

async function postAction(url, payload) {
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  fetchHistory({ force: true });
}

refreshBtn.addEventListener("click", () => fetchHistory({ force: true }));

clearBtn.addEventListener("click", () => {
  const ok = confirm("ピン留めしていない履歴をすべて削除します。よろしいですか？");
  if (!ok) return;
  postAction("/api/clear");
});

function renderHistory(items) {
  historyListEl.innerHTML = "";

  if (items.length === 0) {
    emptyMessageEl.hidden = false;
    return;
  }
  emptyMessageEl.hidden = true;

  for (const item of items) {
    historyListEl.appendChild(buildHistoryItem(item));
  }
}

function buildHistoryItem(item) {
  const li = document.createElement("li");
  li.className = "history-item" + (item.pinned ? " is-pinned" : "");

  const head = document.createElement("div");
  head.className = "history-item__head";

  const meta = document.createElement("div");
  meta.className = "history-item__meta";

  const kindBadge = document.createElement("span");
  if (item.kind === "fm_xml") {
    kindBadge.className = "badge badge--fm";
    kindBadge.textContent = item.snippet_type ? `FileMaker: ${item.snippet_type}` : "FileMaker XML";
  } else {
    kindBadge.className = "badge badge--text";
    kindBadge.textContent = "テキスト";
  }
  meta.appendChild(kindBadge);

  const ts = document.createElement("span");
  ts.className = "timestamp";
  ts.textContent = formatTimestamp(item.timestamp);
  meta.appendChild(ts);

  head.appendChild(meta);

  const actions = document.createElement("div");
  actions.className = "history-item__actions";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "btn btn--small btn--copy";
  copyBtn.textContent = "コピーに戻す";
  copyBtn.addEventListener("click", async () => {
    const original = copyBtn.textContent;
    await postAction("/api/copy", { id: item.id });
    copyBtn.textContent = "コピーしました";
    setTimeout(() => (copyBtn.textContent = original), 1200);
  });

  const pinBtn = document.createElement("button");
  pinBtn.type = "button";
  pinBtn.className = "btn btn--small btn--pin" + (item.pinned ? " is-active" : "");
  pinBtn.textContent = item.pinned ? "ピン留め中" : "ピン留め";
  pinBtn.addEventListener("click", () => postAction("/api/pin", { id: item.id }));

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn btn--small btn--delete";
  deleteBtn.textContent = "削除";
  deleteBtn.addEventListener("click", () => {
    const ok = confirm("この履歴を削除します。よろしいですか？");
    if (!ok) return;
    postAction("/api/delete", { id: item.id });
  });

  actions.appendChild(copyBtn);
  actions.appendChild(pinBtn);
  actions.appendChild(deleteBtn);
  head.appendChild(actions);

  li.appendChild(head);

  if (item.kind === "fm_xml") {
    const blocks = document.createElement("div");
    blocks.className = "fm-blocks";

    const headerBlock = document.createElement("div");
    headerBlock.className = "fm-block";
    const headerLabel = document.createElement("div");
    headerLabel.className = "fm-block__label";
    const lengthInfo =
      item.header_length_value !== null && item.header_length_value !== undefined
        ? `（データ長として解釈: ${item.header_length_value} バイト）`
        : "";
    headerLabel.textContent = `制御コード部分（${item.format_name}）${lengthInfo}`;
    const headerBody = document.createElement("pre");
    headerBody.className = "fm-block__body header-block__body";
    headerBody.textContent = item.header_hex;
    headerBlock.appendChild(headerLabel);
    headerBlock.appendChild(headerBody);

    const xmlBlock = document.createElement("div");
    xmlBlock.className = "fm-block";

    const xmlLabelRow = document.createElement("div");
    xmlLabelRow.className = "fm-block__label fm-block__label--row";
    const xmlLabel = document.createElement("span");
    xmlLabel.textContent = `XML部分（編集可）${item.root_tag ? `（ルート要素: <${item.root_tag}>）` : ""}`;
    const dirtyHint = document.createElement("span");
    dirtyHint.className = "dirty-hint";
    dirtyHint.textContent = "未保存の変更があります";
    dirtyHint.hidden = !editingXml.has(item.id);
    xmlLabelRow.appendChild(xmlLabel);
    xmlLabelRow.appendChild(dirtyHint);

    const xmlTextarea = document.createElement("textarea");
    xmlTextarea.className = "fm-block__body fm-block__editor";
    xmlTextarea.spellcheck = false;
    xmlTextarea.value = editingXml.has(item.id) ? editingXml.get(item.id) : item.xml_pretty;
    xmlTextarea.addEventListener("input", () => {
      editingXml.set(item.id, xmlTextarea.value);
      dirtyHint.hidden = false;
    });

    const xmlSaveRow = document.createElement("div");
    xmlSaveRow.className = "fm-block__save-row";
    const xmlSaveBtn = document.createElement("button");
    xmlSaveBtn.type = "button";
    xmlSaveBtn.className = "btn btn--small btn--save";
    xmlSaveBtn.textContent = "XMLを保存";
    xmlSaveBtn.addEventListener("click", async () => {
      const original = xmlSaveBtn.textContent;
      xmlSaveBtn.disabled = true;
      try {
        const res = await fetch("/api/update-xml", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: item.id, xml_text: xmlTextarea.value }),
        });
        const data = await res.json();
        if (data.ok) {
          editingXml.delete(item.id);
          xmlSaveBtn.textContent = "保存しました";
          fetchHistory({ force: true });
        } else {
          xmlSaveBtn.textContent = "保存に失敗しました";
        }
      } catch (e) {
        xmlSaveBtn.textContent = "保存に失敗しました";
      }
      setTimeout(() => {
        xmlSaveBtn.textContent = original;
        xmlSaveBtn.disabled = false;
      }, 1500);
    });
    xmlSaveRow.appendChild(xmlSaveBtn);

    xmlBlock.appendChild(xmlLabelRow);
    xmlBlock.appendChild(xmlTextarea);
    xmlBlock.appendChild(xmlSaveRow);

    blocks.appendChild(headerBlock);
    blocks.appendChild(xmlBlock);
    li.appendChild(blocks);
  } else {
    const textBlock = document.createElement("pre");
    textBlock.className = "plain-text-block";
    textBlock.textContent = item.text;
    li.appendChild(textBlock);
  }

  return li;
}

fetchHistory();
setInterval(fetchHistory, POLL_INTERVAL_MS);
