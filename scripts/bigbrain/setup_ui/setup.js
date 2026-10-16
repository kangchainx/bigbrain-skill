"use strict";
const $ = (id) => document.getElementById(id);
const token = location.hash.slice(1);
let baseUrl = "";
let recommended = null;
const steps = ["address-step", "key-step", "model-step", "done-step"];

function showStep(index) {
  steps.forEach((id, i) => { $(id).hidden = i !== index; });
  document.querySelectorAll("nav li").forEach((item, i) => {
    if (i === index) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
  $("error").hidden = true;
  $("status").textContent = "";
  const focus = ["base-url", "api-key", "model-step", "done-step"][index];
  $(focus).focus();
}
function fail(error) {
  $("error").textContent = error.message;
  $("error").hidden = false;
}
function busy(message) {
  document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = Boolean(message); });
  $("status").textContent = message;
  $("error").hidden = true;
}
async function request(path, values) {
  let response;
  try {
    response = await fetch(path, {method: "POST", headers: {
      "Content-Type": "application/json", "X-Bigbrain-Token": token,
    }, body: JSON.stringify(values)});
  } catch {
    throw new Error("配置连接已断开或过期，请让 Codex 重新打开配置页面。");
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败，请重试。");
  return result;
}
$("address-form").addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    const raw = $("base-url").value.trim();
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:" || !parsed.hostname || parsed.username || parsed.password || parsed.search || parsed.hash || /\s/.test(raw)) {
      throw new Error("请输入有效的 HTTPS API 地址，不包含用户名、密码、查询参数或片段。");
    }
    baseUrl = raw.replace(/\/+$/, "").replace(/\/v1$/, "");
    $("provider").textContent = baseUrl;
    showStep(1);
  } catch (error) { fail(error); }
});
$("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  busy("正在连接服务商，查询模型列表…");
  try {
    const result = await request("/models", {base_url: baseUrl, api_key: $("api-key").value.trim()});
    $("api-key").value = "";
    recommended = result.recommended_model;
    $("recommended-card").hidden = !recommended;
    $("recommended-id").textContent = recommended || "";
    const radios = document.querySelectorAll('input[name="model-kind"]');
    radios[0].checked = Boolean(recommended);
    radios[1].checked = false;
    $("model-select").replaceChildren(new Option("请选择模型", ""));
    result.models.filter((model) => model !== recommended).forEach((model) => {
      $("model-select").add(new Option(model, model));
    });
    $("catalogue-note").textContent = recommended
      ? "推荐 Claude Opus 5.5；也可以展开其他模型自行选择。"
      : "此接口未返回 Claude Opus 5.5，请从其他模型中选择。";
    otherSelection();
    showStep(2);
  } catch (error) { fail(error); }
  finally {
    document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = false; });
    $("status").textContent = "";
  }
});
function otherSelection() {
  const other = document.querySelector('input[name="model-kind"]:checked')?.value === "other";
  $("other-models").hidden = !other;
  $("model-select").required = other;
}
document.querySelectorAll('input[name="model-kind"]').forEach((radio) => radio.addEventListener("change", otherSelection));
$("model-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const chosen = document.querySelector('input[name="model-kind"]:checked')?.value;
  if (!chosen) {
    fail(new Error("请展开其他模型并选择一个模型。"));
    return;
  }
  const model = chosen === "recommended" ? recommended : $("model-select").value;
  busy("正在验证模型，成功后将自动保存…");
  try {
    const result = await request("/save", {model});
    $("saved-model").textContent = result.model;
    if (result.environment_overrides.length) {
      $("override-warning").textContent = "配置已保存，但这些环境变量仍会优先生效：" + result.environment_overrides.join(", ");
      $("override-warning").hidden = false;
    }
    showStep(3);
    $("cancel").hidden = true;
  } catch (error) { fail(error); }
  finally {
    document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = false; });
    $("status").textContent = "";
  }
});
$("back-address").addEventListener("click", () => { $("api-key").value = ""; showStep(0); });
$("back-key").addEventListener("click", () => showStep(1));
$("cancel").addEventListener("click", async () => {
  try {
    await request("/cancel", {});
    $("api-key").value = "";
    document.querySelectorAll("section, nav").forEach((item) => { item.hidden = true; });
    $("cancel").hidden = true;
    $("status").textContent = "已取消，原有配置未改变。可以关闭此页面。";
  } catch (error) { fail(error); }
});
if (!token) {
  fail(new Error("缺少配置会话，请使用 Codex 提供的完整链接打开此页面。"));
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
} else $("base-url").focus();
