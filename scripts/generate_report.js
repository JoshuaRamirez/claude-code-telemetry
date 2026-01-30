#!/usr/bin/env node
/**
 * Generate productivity report as PDF
 *
 * Prerequisites: npm install puppeteer (in reports folder)
 * Usage: node generate_report.js
 */

const fs = require('fs');
const path = require('path');

const REPORTS_DIR = path.join(__dirname, '..', 'reports');
const HTML_FILE = path.join(REPORTS_DIR, 'productivity_report.html');
const PDF_FILE = path.join(REPORTS_DIR, `productivity_report_${new Date().toISOString().split('T')[0]}.pdf`);

async function generatePDF() {
    console.log('Generating PDF from HTML report...');

    // Check if HTML exists
    if (!fs.existsSync(HTML_FILE)) {
        console.error('HTML report not found. Run the dashboard SQL first to update the HTML.');
        process.exit(1);
    }

    let puppeteer;
    try {
        puppeteer = require('puppeteer');
    } catch (e) {
        console.error('Puppeteer not installed. Run: npm install puppeteer');
        console.log('Or open the HTML file in a browser and use Ctrl+P to print to PDF.');
        process.exit(1);
    }

    console.log('Launching browser...');
    const browser = await puppeteer.launch({ headless: 'new' });
    const page = await browser.newPage();

    console.log('Loading HTML report...');
    await page.goto(`file://${HTML_FILE.replace(/\\/g, '/')}`, {
        waitUntil: 'networkidle0',
        timeout: 60000
    });

    // Wait for mermaid charts to render
    console.log('Waiting for charts to render...');
    await new Promise(r => setTimeout(r, 3000));

    console.log('Generating PDF...');
    await page.pdf({
        path: PDF_FILE,
        format: 'A4',
        printBackground: true,
        margin: { top: '20px', bottom: '20px', left: '20px', right: '20px' }
    });

    await browser.close();
    console.log(`PDF saved to: ${PDF_FILE}`);
}

generatePDF().catch(err => {
    console.error('Error:', err.message);
    process.exit(1);
});
