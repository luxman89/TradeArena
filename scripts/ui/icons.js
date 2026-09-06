// A small, fixed SVG vocabulary. Icons supplement text; icon-only controls need a label.
const paths = {
  arrow: "M5 12h14m-6-6 6 6-6 6",
  refresh:
    "M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1",
  record: "M7 3h10v18H7zM10 8h4m-4 4h4m-4 4h4",
};
export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const path = document.createElementNS(svg.namespaceURI, "path");
  for (const [key, value] of Object.entries({
    viewBox: "0 0 24 24",
    width: "18",
    height: "18",
    fill: "none",
    stroke: "currentColor",
    "stroke-width": "1.5",
    "aria-hidden": "true",
    focusable: "false",
  }))
    svg.setAttribute(key, value);
  path.setAttribute("d", paths[name] || paths.record);
  svg.append(path);
  return svg;
}
