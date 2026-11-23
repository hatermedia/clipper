(function () {
  const year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();

  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = button.getAttribute("data-copy") || "";
      try {
        await navigator.clipboard.writeText(text);
        const original = button.textContent;
        button.textContent = "Copied";
        setTimeout(() => { button.textContent = original; }, 1600);
      } catch (error) {
        button.textContent = "Select manually";
        setTimeout(() => { button.textContent = "Copy"; }, 1600);
      }
    });
  });

  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const id = link.getAttribute("href");
      if (!id || id === "#") return;
      const target = document.querySelector(id);
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
})();
