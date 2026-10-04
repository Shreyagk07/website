document.documentElement.classList.add("js");
try {
  if (localStorage.getItem("motion") === "off") document.documentElement.classList.add("motion-off");
} catch (_) { /* storage unavailable: motion stays on */ }
