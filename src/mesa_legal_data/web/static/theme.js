// MESA Legal Data Theme Manager (POLISH-007)
(() => {
  function getStoredTheme() {
    return localStorage.getItem("mesa_theme") || "system";
  }

  function resolveDark(preference) {
    if (preference === "dark") return true;
    if (preference === "light") return false;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function applyTheme(preference) {
    const isDark = resolveDark(preference);
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    const metaColor = document.querySelector('meta[name="theme-color"]');
    if (metaColor) {
      metaColor.setAttribute("content", isDark ? "#080a0f" : "#f4f6f9");
    }
  }

  // Initial apply
  applyTheme(getStoredTheme());

  // Listen for system preference changes
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (getStoredTheme() === "system") {
        applyTheme("system");
      }
    });
  }

  window.MesaTheme = {
    get: getStoredTheme,
    set: function (mode) {
      if (["system", "light", "dark"].includes(mode)) {
        localStorage.setItem("mesa_theme", mode);
        applyTheme(mode);
      }
    },
  };
})();
