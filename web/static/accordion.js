function toggleAccordion(caret) {
  var content = caret.parentElement.nextElementSibling;
  if (content.style.display === "flex") {
    content.style.display = "none";
    caret.classList.remove("open");
  } else {
    content.style.display = "flex";
    caret.classList.add("open");
  }
}