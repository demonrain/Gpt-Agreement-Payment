<template>
  <section class="step-fade-in">
    <div class="term-divider" data-tail="──────────">步骤 12: Daemon</div>
    <h2 class="step-h">$&nbsp;Daemon 参数<span class="term-cursor"></span></h2>
    <p class="step-sub" v-if="!isDaemon" style="color: var(--warn)">当前模式不是 daemon，跳过即可。</p>

    <div v-if="isDaemon" class="form-stack">
      <TermField v-model="form.target_ok_accounts" label="目标可用号数 · target_ok_accounts" type="number" />
      <TermField v-model="form.usage_pool" label="补号池 · usage_pool（gpt-team account_usage）" type="text" />
      <TermField v-model="form.poll_interval_s" label="池已满时轮询间隔秒 · poll_interval_s" type="number" />
      <TermField v-model="form.rate_limit_per_hour" label="每小时注册上限 · rate_limit_per_hour（0=不限）" type="number" />
      <TermField v-model="form.rate_limit_per_day" label="每日注册上限 · rate_limit_per_day（0=不限）" type="number" />
      <TermField v-model="form.min_interval_between_runs_s" label="两次尝试最小间隔秒 · min_interval_between_runs_s（GoPay 建议 300–600）" type="number" />
      <TermField v-model="form.jitter_min" label="开跑前抖动最小秒 · jitter_min" type="number" />
      <TermField v-model="form.jitter_max" label="开跑前抖动最大秒 · jitter_max" type="number" />
      <TermField v-model="form.max_consecutive_failures" label="连续失败上限 · max_consecutive_failures" type="number" />
      <TermField v-model="form.consecutive_fail_cooldown_s" label="连续失败后冷却秒 · consecutive_fail_cooldown_s" type="number" />
      <TermField v-model="form.seat_limit" label="席位上限 · seat_limit" type="number" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useWizardStore } from "../../stores/wizard";
import TermField from "../term/TermField.vue";

const store = useWizardStore();
const isDaemon = computed(() => store.answers.mode?.mode === "daemon");

function buildDaemonForm(raw: Record<string, unknown>) {
  const rl = (raw.rate_limit as Record<string, unknown> | undefined) ?? {};
  const jraw = raw.jitter_before_run_s;
  const j = Array.isArray(jraw) && jraw.length >= 2 ? jraw : [];
  return {
    target_ok_accounts: Number(raw.target_ok_accounts ?? 20),
    usage_pool: String(raw.usage_pool ?? "recovery"),
    poll_interval_s: Number(raw.poll_interval_s ?? 600),
    rate_limit_per_hour: Number(raw.rate_limit_per_hour ?? rl.per_hour ?? 0),
    rate_limit_per_day: Number(raw.rate_limit_per_day ?? rl.per_day ?? 30),
    min_interval_between_runs_s: Number(raw.min_interval_between_runs_s ?? 0),
    jitter_min: Number(raw.jitter_min ?? j[0] ?? 60),
    jitter_max: Number(raw.jitter_max ?? j[1] ?? 180),
    max_consecutive_failures: Number(raw.max_consecutive_failures ?? 5),
    consecutive_fail_cooldown_s: Number(raw.consecutive_fail_cooldown_s ?? 1800),
    seat_limit: Number(raw.seat_limit ?? 5),
  };
}

const init = store.answers.daemon ?? {};
const form = ref(buildDaemonForm(init as Record<string, unknown>));

watch(form, () => {
  if (!isDaemon.value) {
    store.setAnswer("daemon", {});
    return;
  }
  store.setAnswer("daemon", form.value);
  store.saveToServer();
}, { deep: true });
</script>
