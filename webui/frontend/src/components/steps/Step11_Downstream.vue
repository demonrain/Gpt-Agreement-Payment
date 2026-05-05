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
import { ref, watch } from "vue";
import { useWizardStore } from "../../stores/wizard";
import type { PreflightResult } from "../../api/client";
import TermField from "../term/TermField.vue";
import TermBtn from "../term/TermBtn.vue";
import TermToggle from "../term/TermToggle.vue";

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
  auto_push: saInit.auto_push ?? true,
  skip_default_group_bind: saInit.skip_default_group_bind ?? true,
});
const tsLoading = ref(false);
const cpaLoading = ref(false);
const sub2apiLoading = ref(false);
const tsResult = ref<PreflightResult | null>(null);
const cpaResult = ref<PreflightResult | null>(null);
const sub2apiResult = ref<PreflightResult | null>(null);

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
