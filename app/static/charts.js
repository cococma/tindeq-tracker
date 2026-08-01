/* Shared Plotly theming for TrainingJournal.
 *
 * Categorical palette validated (dark surface #1a1208): CVD-safe, in-band.
 * Grip identity has a FIXED color; hand is encoded by line dash, never a 5th hue.
 */

const TJ = {
    surface: "#1a1208",
    ink:     "#d4b896",
    muted:   "#7a6040",
    grid:    "#2e2412",
    hero:    "#8aaa3a",   // single-series force traces
    amber:   "#c8a84b",   // reference lines (targets)

    gripColor: {
        half_crimp: "#6f8f2d",
        full_crimp: "#b58a2f",
        open_hand:  "#3f83cf",
        pinch:      "#c65f85",
    },
    gripLabel: {
        half_crimp: "Half Crimp",
        full_crimp: "Full Crimp",
        open_hand:  "Open Hand",
        pinch:      "Pinch",
    },
    handDash: { right: "solid", left: "dash", both: "dot" },

    layout(overrides = {}) {
        return Object.assign({
            paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor:  "rgba(0,0,0,0)",
            font: { family: "SF Mono, ui-monospace, Menlo, monospace", size: 12, color: TJ.ink },
            margin: { l: 55, r: 20, t: 30, b: 45 },
            xaxis: TJ.axis(),
            yaxis: TJ.axis(),
            hovermode: "closest",
            hoverlabel: { bgcolor: "#2a1e0e", bordercolor: "#3d5228", font: { color: "#e8d9bd" } },
            legend: { orientation: "h", y: -0.18, font: { color: TJ.ink } },
        }, overrides);
    },

    axis(overrides = {}) {
        return Object.assign({
            gridcolor: TJ.grid,
            zeroline: false,
            linecolor: TJ.grid,
            tickcolor: TJ.grid,
            tickfont: { color: TJ.muted },
            titlefont: { color: TJ.muted },
        }, overrides);
    },

    config: { displayModeBar: false, responsive: true },

    empty(el, message) {
        el.innerHTML = `<div class="empty">${message}</div>`;
    },

    // Defer chart work until the element scrolls near the viewport.
    whenVisible(el, fn) {
        new IntersectionObserver((entries, obs) => {
            if (entries[0].isIntersecting) {
                obs.disconnect();
                fn();
            }
        }, { rootMargin: "200px" }).observe(el);
    },
};
