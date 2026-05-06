<template>
  <section class="step-fade-in">
    <div class="term-divider" data-tail="──────────">步骤 11: 下游推送</div>
    <h2 class="step-h">$&nbsp;下游推送 (全部可选)<span class="term-cursor"></span></h2>

    <div class="term-divider" style="margin-top:8px">gpt-team</div>
    <TermToggle v-model="ts.enabled">启用 gpt-team</TermToggle>
    <div v-if="ts.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="ts.base_url" label="Base URL · base_url" />
      <TermField v-model="ts.username" label="用户名 · username" />
      <TermField v-model="ts.password" label="密码 · password" type="password" />
      <div class="step-actions">
        <TermBtn :loading="tsLoading" @click="testTs">登录测试</TermBtn>
      </div>
      <div v-if="tsResult" class="result-block" :class="`result--${tsResult.status}`">
        <div class="result-head">
          <span class="result-icon">{{ icon(tsResult.status) }}</span>
          <span>{{ tsResult.message }}</span>
        </div>
      </div>
    </div>

    <div class="term-divider" style="margin-top:20px">CPA</div>
    <TermToggle v-model="cpa.enabled">启用 CPA</TermToggle>
    <div v-if="cpa.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="cpa.base_url" label="Base URL · base_url" />
      <TermField v-model="cpa.admin_key" label="Admin Key · admin_key" type="password" />
      <div class="step-actions">
        <TermBtn :loading="cpaLoading" @click="testCpa">健康检查</TermBtn>
      </div>
      <div v-if="cpaResult" class="result-block" :class="`result--${cpaResult.status}`">
        <div class="result-head">
          <span class="result-icon">{{ icon(cpaResult.status) }}</span>
          <span>{{ cpaResult.message }}</span>
        </div>
      </div>
    </div>

    <div class="term-divider" style="margin-top:20px">sub2api</div>
    <TermToggle v-model="sub2api.enabled">启用 sub2api</TermToggle>
    <div v-if="sub2api.enabled" class="form-stack" style="margin-top:12px">
      <TermField v-model="sub2api.base_url" label="Base URL · base_url" placeholder="https://your-sub2api.example.com" />
      <TermField v-model="sub2api.token" label="Admin Token · token" type="password" />
      <TermSelect
        v-model="sub2api.count_platform"
        label="daemon 计数平台 · count_platform"
        :options="platformOptions"
      />
      <TermSelect
        v-model="sub2api.count_status"
        label="daemon 计数状态 · count_status"
        :options="statusOptions"
      />
      <div class="step-actions" style="margin-top:0">
        <TermBtn :loading="sub2apiGroupsLoading" @click="loadSub2apiGroups">拉取分组</TermBtn>
      </div>
      <TermSelect
        v-model="sub2api.count_group"
        label="daemon 计数分组 · count_group"
        :options="countGroupOptions"
      />
      <TermSelect
        v-model="sub2api.push_group_id"
        label="推送目标分组 · push_group_id"
        :options="pushGroupOptions"
      />
      <div v-if="sub2apiGroupsError" class="result-block result--fail">
        <div class="result-head">
          <span class="result-icon">✗</span>
          <span>{{ sub2apiGroupsError }}</span>
        </div>
      </div>
      <TermToggle v-model="sub2api.auto_push">支付成功后自动推送</TermToggle>
      <TermToggle v-model="sub2api.skip_default_group_bind">跳过默认分组绑定</TermToggle>
      <div class="step-actions">
        <TermBtn :loading="sub2apiLoading" @click="testSub2api">连通测试</TermBtn>
      </div>
      <div v-if="sub2apiResult" class="result-block" :class="`result--${sub2apiResult.status}`">
        <div class="result-head">
          <span class="result-icon">{{ icon(sub2apiResult.status) }}</span>
          <span>{{ sub2apiResult.message }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useWizardStore } from "../../stores/wizard";
import { api } from "../../api/client";
import type { PreflightResult } from "../../api/client";
import TermField from "../term/TermField.vue";
import TermBtn from "../term/TermBtn.vue";
import TermToggle from "../term/TermToggle.vue";
import TermSelect from "../term/TermSelect.vue";

const store = useWizardStore();
const tsInit = store.answers.team_system ?? {};
const cpaInit = store.answers.cpa ?? {};
const saInit = store.answers.sub2api ?? {};

const ts = ref({
  enabled: tsInit.enabled ?? false,
  base_url: tsInit.base_url ?? "http://127.0.0.1:3000",
  username: tsInit.username ?? "admin",
  password: tsInit.password ?? "",
});
const cpa = ref({
  enabled: cpaInit.enabled ?? false,
  base_url: cpaInit.base_url ?? "",
  admin_key: cpaInit.admin_key ?? "",
});
const sub2api = ref({
  enabled: saInit.enabled ?? false,
  base_url: saInit.base_url ?? "",
  token: saInit.token ?? "",
  count_platform: saInit.count_platform ?? "openai",
  count_status: saInit.count_status ?? "active",
  // daemon 计数分组："" 表示不过滤；"ungrouped" 表示无分组；或具体 group_id
  count_group: saInit.count_group ?? "",
  // 推送目标分组："" 表示不绑定；具体 group_id 表示导入后批量绑定
  push_group_id: saInit.push_group_id ?? "",
  auto_push: saInit.auto_push ?? true,
  skip_default_group_bind: saInit.skip_default_group_bind ?? true,
});
const tsLoading = ref(false);
const cpaLoading = ref(false);
const sub2apiLoading = ref(false);
const tsResult = ref<PreflightResult | null>(null);
const cpaResult = ref<PreflightResult | null>(null);
const sub2apiResult = ref<PreflightResult | null>(null);
const sub2apiGroupsLoading = ref(false);
const sub2apiGroupsError = ref("");
const sub2apiGroups = ref<{ id: number | string; name: string; platform?: string; status?: string }[]>([]);

const platformOptions = [
  { value: "openai", label: "openai", desc: "ChatGPT / OpenAI" },
  { value: "anthropic", label: "anthropic", desc: "Claude / Anthropic" },
  { value: "gemini", label: "gemini", desc: "Gemini / Google" },
  { value: "antigravity", label: "antigravity", desc: "antigravity" },
];

const statusOptions = [
  { value: "active", label: "active", desc: "启用" },
  { value: "inactive", label: "inactive", desc: "停用" },
  { value: "error", label: "error", desc: "错误" },
  { value: "", label: "(不传)", desc: "不传 status 参数（服务端默认）" },
];

const countGroupOptions = computed(() => {
  const opts = [
    { value: "", label: "全部分组", desc: "不加 group 过滤（统计全部账号）" },
    { value: "ungrouped", label: "未分组", desc: "group=ungrouped" },
  ];
  for (const g of sub2apiGroups.value) {
    opts.push({ value: String(g.id), label: `${g.name} (#${g.id})`, desc: "" });
  }
  return opts;
});

const pushGroupOptions = computed(() => {
  const opts = [
    { value: "", label: "不绑定分组", desc: "导入后不做 group 绑定" },
  ];
  for (const g of sub2apiGroups.value) {
    opts.push({ value: String(g.id), label: `${g.name} (#${g.id})`, desc: "" });
  }
  return opts;
});

async function testTs() {
  tsLoading.value = true;
  try {
    tsResult.value = await store.runPreflight("team_system", {
      base_url: ts.value.base_url,
      username: ts.value.username,
      password: ts.value.password,
    });
  } finally { tsLoading.value = false; }
}
async function testCpa() {
  cpaLoading.value = true;
  try {
    cpaResult.value = await store.runPreflight("cpa", {
      base_url: cpa.value.base_url,
      admin_key: cpa.value.admin_key,
    });
  } finally { cpaLoading.value = false; }
}
async function testSub2api() {
  sub2apiLoading.value = true;
  try {
    sub2apiResult.value = await store.runPreflight("sub2api", {
      base_url: sub2api.value.base_url,
      token: sub2api.value.token,
    });
  } finally { sub2apiLoading.value = false; }
}

async function loadSub2apiGroups() {
  if (sub2apiGroupsLoading.value) return;
  sub2apiGroupsLoading.value = true;
  sub2apiGroupsError.value = "";
  try {
    const r = await api.get("/inventory/sub2api-groups", {
      params: { platform: sub2api.value.count_platform },
    });
    sub2apiGroups.value = Array.isArray(r.data?.groups) ? r.data.groups : [];
  } catch (e: any) {
    const detail = e?.response?.data?.detail;
    sub2apiGroupsError.value = typeof detail === "string" ? detail : (e?.message || "拉取分组失败");
    sub2apiGroups.value = [];
  } finally {
    sub2apiGroupsLoading.value = false;
  }
}
watch([ts, cpa, sub2api], () => {
  store.setAnswer("team_system", ts.value.enabled ? ts.value : {});
  store.setAnswer("cpa", cpa.value.enabled ? cpa.value : {});
  store.setAnswer("sub2api", sub2api.value.enabled ? sub2api.value : {});
  store.saveToServer();
}, { deep: true });

function icon(s: string) {
  return s === "ok" ? "✓" : s === "fail" ? "✗" : s === "warn" ? "▲" : "○";
}
</script>
