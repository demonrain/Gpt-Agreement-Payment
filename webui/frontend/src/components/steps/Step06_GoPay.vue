<template>
  <section class="step-fade-in">
    <div class="term-divider" data-tail="──────────">步骤 06: GoPay 账号</div>
    <h2 class="step-h">$&nbsp;GoPay (印尼 e-wallet)<span class="term-cursor"></span></h2>
    <p class="step-sub">每个 ChatGPT Plus 订阅消耗 1 次 WhatsApp OTP + 2 次 PIN 输入。Lite 账号 (无印尼 KYC) 月限额约 IDR 2M ≈ 5-6 单。</p>

    <div class="form-stack">
      <TermField v-model="form.country_code" label="国家码 · country_code" placeholder="86 (中国大陆) / 62 (印尼)" />
      <TermField v-model="form.phone_number" label="手机号 · phone_number" placeholder="不带国家码，11 位数字" />
      <TermField v-model="form.pin" label="6 位 PIN · pin" type="password" placeholder="登录 GoJek/GoPay 时设的 PIN" />
      <TermSelect
        v-model="form.otp_source"
        label="OTP 接收方式 · otp_source"
        :options="otpSourceOptions"
      />
      <TermField v-model.number="form.otp_timeout" label="OTP 等待超时秒数" type="number" />
      <template v-if="form.otp_source === 'adb'">
        <TermField v-model="form.adb_serial" label="ADB 设备序列号 · adb_serial" placeholder="先点「扫描 ADB 设备」获取正确地址" />
        <div class="adb-scan-settings">
          <TermToggle v-model="form.adb_scan_lan">启用局域网 ADB 扫描</TermToggle>
          <div class="adb-scan-grid">
            <TermField v-model="form.adb_scan_subnets" label="扫描网段 · scan_subnets" placeholder="192.168.0.0/24 或 192.168.0.55/32" />
            <TermField v-model="form.adb_scan_ports" label="扫描端口 · scan_ports" placeholder="5555,5557,7555" />
          </div>
        </div>
        <div class="adb-actions">
          <button class="btn-term" :disabled="adbChecking" @click="listAdbDevices">
            {{ adbChecking ? '检测中...' : '$ 扫描 ADB 设备' }}
          </button>
          <button class="btn-term" :disabled="adbTesting" @click="testAdbConnection">
            {{ adbTesting ? '测试中...' : '$ 测试连接 + WhatsApp' }}
          </button>
        </div>
        <div v-if="adbScanError" class="adb-test-result adb-test--fail">
          <div class="adb-test-status">✗ {{ adbScanError }}</div>
        </div>
        <div v-if="adbDevices.length" class="adb-device-list">
          <div class="adb-device-header">检测到的设备：</div>
          <div
            v-for="d in adbDevices" :key="d.serial"
            class="adb-device-item"
            :class="{ 'adb-device-item--active': d.serial === form.adb_serial }"
            @click="form.adb_serial = d.serial"
          >
            <span class="adb-device-serial">{{ d.serial }}</span>
            <span class="adb-device-state" :class="d.state === 'device' ? 'state-ok' : 'state-err'">{{ d.state }}</span>
            <span v-if="d.model" class="adb-device-model">{{ d.model }}</span>
            <span class="adb-device-use">← 点击使用</span>
          </div>
        </div>
        <div v-if="adbHostHint" class="adb-host-hint">{{ adbHostHint }}</div>
        <div v-if="adbQuickPorts.length" class="adb-quick-ports">
          <span class="adb-quick-label">常见模拟器端口：</span>
          <button
            v-for="p in adbQuickPorts" :key="p.name"
            class="btn-port"
            @click="form.adb_serial = p.serial"
          >{{ p.name }} ({{ p.serial }})</button>
        </div>
        <div v-if="adbTestResult" class="adb-test-result" :class="'adb-test--' + adbTestResult.status">
          <div class="adb-test-status">{{ adbTestResult.status === 'ok' ? '✓ 全部通过' : adbTestResult.status === 'warn' ? '⚠ 部分通过' : '✗ 检测失败' }}</div>
          <div v-for="c in adbTestResult.checks" :key="c.name" class="adb-check-item">
            <span :class="'check-' + c.status">{{ c.status === 'ok' ? '✓' : c.status === 'warn' ? '⚠' : '✗' }}</span>
            {{ c.message }}
            <span v-if="c.details" class="adb-check-detail">{{ c.details }}</span>
          </div>
        </div>
        <div class="unlink-section">
          <TermToggle v-model="form.auto_unlink">支付成功后自动 Unlink GoPay → OpenAI</TermToggle>
          <p class="unlink-hint">防止下次 linking 出现 406 "account already linked"。需要 ADB 能操作 GoPay App 的 UI。</p>
          <div class="adb-actions">
            <button class="btn-term unlink-btn" :disabled="unlinkRunning" @click="manualUnlink">
              {{ unlinkRunning ? '解绑中...' : '$ 手动 Unlink GoPay → OpenAI' }}
            </button>
          </div>
          <div v-if="unlinkResult" class="adb-test-result" :class="unlinkResult.ok ? 'adb-test--ok' : 'adb-test--fail'">
            <div class="adb-test-status">{{ unlinkResult.ok ? '✓' : '✗' }} {{ unlinkResult.message }}</div>
          </div>
        </div>
      </template>
      <template v-if="form.otp_source === 'appium'">
        <TermField v-model="form.appium_url" label="Appium 服务地址 · appium_url" placeholder="http://127.0.0.1:4723" />
        <TermField v-model="form.adb_serial" label="ADB 设备序列号 · adb_serial" placeholder="emulator-5554（可选）" />
      </template>
      <TermSelect
        v-if="form.otp_source === 'auto'"
        v-model="form.whatsapp_engine"
        label="WhatsApp 引擎"
        :options="engineOptions"
      />
    </div>

    <RouterLink v-if="form.otp_source === 'auto'" class="wa-login-entry" to="/whatsapp">
      <span class="wa-login-prompt">$</span>
      WhatsApp 登录 / 扫码接收 GoPay OTP
    </RouterLink>

    <div class="hint-box">
      <template v-if="form.otp_source === 'auto'">
        <p>默认模式：扫码连接 WhatsApp Web 后，后台自动监听消息并读取 GoPay OTP。</p>
      </template>
      <template v-else-if="form.otp_source === 'adb'">
        <p>ADB 模式：通过 ADB 连接 Android 虚拟机/真机，读取 WhatsApp 通知栏中的 OTP。</p>
        <p>前置条件：1. Android 设备已安装 WhatsApp 并登录 GoPay 绑定号码</p>
        <p>2. ADB 已连接（执行 <code>adb devices</code> 可见设备）</p>
        <p>3. WhatsApp 通知未被关闭</p>
      </template>
      <template v-else-if="form.otp_source === 'appium'">
        <p>Appium 模式：通过 Appium 控制 Android 虚拟机中的 WhatsApp App，自动打开对话读取 OTP。</p>
        <p>前置条件：1. Appium Server 已启动（<code>appium</code>）</p>
        <p>2. Android 设备已连接 ADB，WhatsApp 已登录</p>
        <p>3. 安装依赖：<code>pip install Appium-Python-Client</code></p>
      </template>
      <template v-else>
        <p>手动模式：运行时会弹出 OTP 输入框，需要人工查看 WhatsApp 后填入。</p>
      </template>
      <p>PIN 配置后自动用，绑定 + 扣款各用一次。</p>
      <p>同号重复绑定时第一次会返 406「account already linked」，gopay.py 会自动重试一次。</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { useWizardStore } from "../../stores/wizard";
import { api, type PreflightCheck, type PreflightResult } from "../../api/client";
import TermField from "../term/TermField.vue";
import TermSelect from "../term/TermSelect.vue";
import TermToggle from "../term/TermToggle.vue";

const store = useWizardStore();
const init = store.answers.gopay ?? {};
const initOtp = init.otp ?? {};
const form = ref({
  country_code: init.country_code ?? "86",
  phone_number: init.phone_number ?? "",
  pin: init.pin ?? "",
  otp_source: init.otp_source ?? "auto",
  otp_timeout: init.otp_timeout ?? initOtp.timeout ?? 300,
  adb_serial: init.adb_serial ?? "127.0.0.1:7555",
  adb_scan_lan: init.adb_scan_lan ?? true,
  adb_scan_subnets: init.adb_scan_subnets ?? "192.168.0.0/24",
  adb_scan_ports: init.adb_scan_ports ?? "5555,5557,7555,16348,16384,16416,16448,16480,62001",
  appium_url: init.appium_url ?? "http://127.0.0.1:4723",
  whatsapp_engine: init.whatsapp_engine ?? "baileys",
  auto_unlink: init.auto_unlink ?? false,
});

interface AdbDevice { serial: string; state: string; model: string }
interface AdbLanScan { enabled: boolean; subnets: string[]; ports: number[] }
const adbDevices = ref<AdbDevice[]>([]);
const adbChecking = ref(false);
const adbTesting = ref(false);
const adbTestResult = ref<PreflightResult | null>(null);
const adbLanScan = ref<AdbLanScan | null>(null);

const adbQuickPorts = ref([
  { name: "MuMu", serial: "127.0.0.1:7555" },
  { name: "MuMu 12", serial: "127.0.0.1:16348" },
  { name: "MuMu 12", serial: "127.0.0.1:16384" },
  { name: "雷电", serial: "emulator-5554" },
  { name: "夜神", serial: "127.0.0.1:62001" },
  { name: "BlueStacks", serial: "127.0.0.1:5555" },
]);
const adbHostHint = ref("");

const adbScanError = ref("");

async function listAdbDevices() {
  adbChecking.value = true;
  adbDevices.value = [];
  adbScanError.value = "";
  adbLanScan.value = null;
  try {
    const { data } = await api.get("/preflight/adb/devices", {
      params: {
        scan_lan: form.value.adb_scan_lan,
        scan_subnets: form.value.adb_scan_subnets,
        scan_ports: form.value.adb_scan_ports,
      },
    });
    if (data.ok) {
      adbDevices.value = data.devices ?? [];
      adbLanScan.value = data.lan_scan ?? null;
      if (data.known_ports) {
        adbQuickPorts.value = Object.entries(data.known_ports as Record<string, string>).map(
          ([k, v]) => ({ name: k.replace("mumu12", "MuMu 12").replace("mumu", "MuMu").replace("ldplayer", "雷电").replace("nox", "夜神").replace("bluestacks", "BlueStacks"), serial: v }),
        );
      }
      if (data.hint) adbHostHint.value = data.hint;
      if (!adbDevices.value.length) {
        const scan = adbLanScan.value;
        const scope = scan?.enabled
          ? `已扫描局域网 ${scan.subnets?.join(", ") || "(未检测到网段)"} 端口 ${scan.ports?.join(", ") || "5555/5557"}`
          : "局域网扫描已关闭";
        adbScanError.value = `未检测到任何 ADB 设备。${scope}。请确认设备 IP 在扫描网段内，且 ADB TCP 端口已开启。`;
      }
    } else {
      adbScanError.value = data.error || "扫描失败";
    }
  } catch (e: any) {
    adbScanError.value = e?.response?.data?.detail ?? "请求失败";
  }
  adbChecking.value = false;
}

async function testAdbConnection() {
  adbTesting.value = true;
  adbTestResult.value = null;
  try {
    const { data } = await api.post("/preflight/adb", { adb_serial: form.value.adb_serial });
    adbTestResult.value = data;
  } catch (e: any) {
    adbTestResult.value = {
      status: "fail",
      message: e?.response?.data?.detail ?? "请求失败",
      checks: [],
    };
  }
  adbTesting.value = false;
}

const unlinkRunning = ref(false);
const unlinkResult = ref<{ ok: boolean; message: string } | null>(null);

async function manualUnlink() {
  unlinkRunning.value = true;
  unlinkResult.value = null;
  try {
    const { data } = await api.post("/inventory/gopay-unlink", { adb_serial: form.value.adb_serial });
    unlinkResult.value = data;
  } catch (e: any) {
    unlinkResult.value = { ok: false, message: e?.response?.data?.detail ?? "请求失败" };
  }
  unlinkRunning.value = false;
}

const otpSourceOptions = [
  { value: "auto", label: "WhatsApp Web (默认)", desc: "通过 WhatsApp Web 扫码自动接收" },
  { value: "adb", label: "ADB 虚拟机通知", desc: "读取 Android 虚拟机/真机 WhatsApp 通知栏" },
  { value: "appium", label: "Appium 自动化", desc: "通过 Appium 控制 WhatsApp App 读取消息" },
  { value: "manual", label: "手动输入", desc: "运行时手动查看 WhatsApp 后填入 OTP" },
];

const engineOptions = [
  { value: "baileys", label: "Baileys (推荐)", desc: "直连 WhatsApp multi-device socket，启动更轻" },
  { value: "wwebjs", label: "whatsapp-web.js", desc: "Chromium 路径，兼容旧环境 / 调试用" },
];

watch(form, () => {
  store.setAnswer("gopay", form.value);
  store.saveToServer();
}, { deep: true });
</script>

<style scoped>
.hint-box {
  margin-top: 24px;
  padding: 12px 14px;
  border: 1px dashed var(--border);
  background: var(--bg-panel);
  font-size: 12px;
  color: var(--fg-tertiary);
}
.hint-box p { margin: 4px 0; }
.wa-login-entry {
  margin-top: 18px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--accent);
  color: var(--accent);
  background: rgba(93, 255, 174, 0.06);
  text-decoration: none;
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 700;
}
.wa-login-entry:hover {
  background: rgba(93, 255, 174, 0.12);
}
.wa-login-prompt {
  color: var(--fg-primary);
}
/* ADB 检测 */
.adb-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.adb-scan-settings {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  background: var(--bg-base);
}
.adb-scan-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  margin-top: 8px;
}
.btn-term {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  color: var(--accent);
  padding: 8px 14px;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all 80ms;
}
.btn-term:hover:not(:disabled) { border-color: var(--accent); background: rgba(93,255,174,0.08); }
.btn-term:disabled { opacity: 0.4; cursor: wait; }
.adb-device-list {
  margin-top: 10px;
  border: 1px solid var(--border);
  background: var(--bg-base);
}
.adb-device-header {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 700;
  color: var(--fg-tertiary);
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
}
.adb-device-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  font-size: 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
}
.adb-device-item:last-child { border-bottom: 0; }
.adb-device-item:hover { background: rgba(93,255,174,0.04); }
.adb-device-item--active { background: rgba(93,255,174,0.08); border-left: 3px solid var(--accent); }
.adb-device-serial { font-family: monospace; color: var(--fg-primary); font-weight: 700; }
.adb-device-state { font-size: 11px; }
.state-ok { color: var(--ok); }
.state-err { color: var(--err); }
.adb-device-model { color: var(--fg-tertiary); font-size: 11px; }
.adb-device-use { margin-left: auto; color: var(--fg-tertiary); font-size: 10px; opacity: 0.5; }
.adb-quick-ports {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.adb-quick-label { font-size: 11px; color: var(--fg-tertiary); }
.btn-port {
  background: var(--bg-base);
  border: 1px solid var(--border);
  color: var(--fg-secondary);
  padding: 4px 10px;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.btn-port:hover { border-color: var(--accent); color: var(--accent); }
.adb-test-result {
  margin-top: 10px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  font-size: 12px;
}
.adb-test--ok { border-color: var(--ok); background: rgba(93,255,174,0.04); }
.adb-test--warn { border-color: #f0c040; background: rgba(240,192,64,0.04); }
.adb-test--fail { border-color: var(--err); background: rgba(255,80,80,0.04); }
.adb-test-status { font-weight: 700; margin-bottom: 6px; }
.adb-check-item { padding: 2px 0; display: flex; align-items: baseline; gap: 6px; }
.check-ok { color: var(--ok); }
.check-warn { color: #f0c040; }
.check-fail { color: var(--err); }
.adb-check-detail { color: var(--fg-tertiary); font-size: 11px; margin-left: 4px; }
.adb-host-hint {
  margin-top: 8px;
  padding: 6px 12px;
  background: rgba(93,180,255,0.08);
  border: 1px solid rgba(93,180,255,0.3);
  color: var(--fg-secondary);
  font-size: 11px;
}
.unlink-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--border);
}
.unlink-hint {
  margin: 4px 0 8px;
  color: var(--fg-tertiary);
  font-size: 11px;
}
.unlink-btn {
  border-color: #f59e0b !important;
  color: #f59e0b !important;
}
.unlink-btn:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.08) !important;
}
@media (max-width: 720px) {
  .adb-scan-grid { grid-template-columns: 1fr; }
}
</style>
