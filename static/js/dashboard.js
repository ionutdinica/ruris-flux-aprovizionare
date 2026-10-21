/*
 * Graficele panoului (Chart.js). Datele vin din pagină, prin json_script:
 *   <canvas data-chart="chart-on-time">  +  <script id="chart-on-time" type="application/json">
 * Ce se desenează și cu ce culori se decide pe server (apps/dashboard/charts.py);
 * aici doar se traduce în opțiunile Chart.js.
 */
(function () {
  "use strict";

  const numbers = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 2 });
  const format = (value, unit) => {
    if (unit === "%") return `${numbers.format(value)}%`;
    if (unit === "lei") return `${numbers.format(value)} lei`;
    return numbers.format(value);
  };

  document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
    const chart = JSON.parse(document.getElementById(canvas.dataset.chart).textContent);
    const isRound = chart.kind === "doughnut";
    const valueAxis = chart.horizontal ? "x" : "y";

    new Chart(canvas, {
      type: chart.kind,
      data: {
        labels: chart.labels,
        datasets: chart.datasets.map((dataset) => ({
          label: dataset.label,
          data: dataset.data,
          backgroundColor: dataset.color,
          borderColor: dataset.color,
          tension: 0.25, // linii ușor rotunjite
          fill: false,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: chart.horizontal ? "y" : "x",
        plugins: {
          legend: { display: isRound || chart.datasets.length > 1, position: "bottom" },
          tooltip: {
            callbacks: {
              label: (item) => `${item.dataset.label}: ${format(item.raw, chart.unit)}`,
            },
          },
        },
        scales: isRound
          ? {}
          : {
              [valueAxis]: {
                beginAtZero: true,
                stacked: chart.stacked,
                max: chart.unit === "%" ? 100 : undefined,
                ticks: { precision: 0, callback: (value) => format(value, chart.unit) },
              },
              [valueAxis === "x" ? "y" : "x"]: { stacked: chart.stacked },
            },
      },
    });
  });
})();
