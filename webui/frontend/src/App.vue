<template>
  <n-config-provider :theme="lightTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
      <RouterView />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider, NDialogProvider, lightTheme, type GlobalThemeOverrides } from "naive-ui";

const themeOverrides: GlobalThemeOverrides = {
  common: {
    fontFamily: "JetBrains Mono, ui-monospace, monospace",
    fontFamilyMono: "JetBrains Mono, ui-monospace, monospace",
    primaryColor: "#b25e1f",
    primaryColorHover: "#8a4413",
    primaryColorPressed: "#6b340c",
    primaryColorSuppl: "#b25e1f",
    successColor: "#1f6638",
    warningColor: "#b25e1f",
    errorColor: "#b91c1c",
    bodyColor: "#faf8f3",
    cardColor: "#ffffff",
    modalColor: "#ffffff",
    popoverColor: "#ffffff",
    tableHeaderColor: "#f0ece1",
    textColorBase: "#1c1a15",
    textColor1: "#1c1a15",
    textColor2: "#3a362e",
    textColor3: "#7a7363",
    borderColor: "#d4cdb9",
    dividerColor: "#d4cdb9",
    inputColor: "#ffffff",
    inputColorDisabled: "#f0ece1",
    actionColor: "#f0ece1",
    hoverColor: "#ede8da",
    borderRadius: "0px",
    borderRadiusSmall: "0px",
  },
  Button: { borderRadiusMedium: "0px", borderRadiusSmall: "0px" },
  Card: { borderRadius: "0px" },
  Input: { borderRadius: "0px" },
  Tag: { borderRadiusSmallRound: "0px" },
};
</script>

<style>
</style>
