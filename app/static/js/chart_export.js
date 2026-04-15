// Export a Chart.js canvas as a PNG without snapshotting surrounding tables.
(function () {
    function triggerDownload(dataUrl, filename) {
        const link = document.createElement("a");
        link.href = dataUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    function downloadChartPng(canvasId, baseName) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !(canvas instanceof HTMLCanvasElement)) {
            console.error("chart_export: no canvas with id", canvasId);
            return;
        }

        const background = getComputedStyle(document.body).backgroundColor || "#ffffff";
        const output = document.createElement("canvas");
        output.width = canvas.width;
        output.height = canvas.height;
        const ctx = output.getContext("2d");
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, output.width, output.height);
        ctx.drawImage(canvas, 0, 0);

        const today = new Date().toISOString().slice(0, 10);
        triggerDownload(output.toDataURL("image/png"), `${baseName}-${today}.png`);
    }

    window.downloadChartPng = downloadChartPng;
})();
