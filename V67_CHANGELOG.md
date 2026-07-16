# Durably v67 - Scan coverage and source register

## Purpose

Every completed scan now states clearly how many and which website pages and documents were actually reviewed. Failed access attempts are kept separate and are never presented as analysed evidence.

## Web interface

A new **Scan coverage and reviewed sources** section is shown directly after the executive summary.

It includes:

- number of website pages reviewed;
- number of PDF/documents reviewed;
- number of domains covered;
- number of failed fetch attempts;
- complete tables of successfully reviewed website pages and documents;
- audience classification and retrieval method for every source;
- a separate expandable list of attempted but inaccessible pages;
- clear identification of pages retrieved through the public text-extraction fallback;
- a **Download source register (CSV)** button.

## Scan-result data

The API response now contains a generic `scan_inventory` object:

- `summary`
- `website_pages`
- `documents`
- `failed_fetches`
- `domains`
- `note`

This works for ordinary website scans and standalone uploaded-document scans.

## Two-page company report

Page 2 now has a separate **Assessment coverage** section. It states:

- website-page count;
- PDF/document count;
- domain count;
- the main reviewed pages and documents, marked as `PAGE` or `DOC`;
- when more reviewed sources are available in the online source register.

The two-page preflight remains active. If necessary, the number of listed sources is reduced before any font size is changed.

## Retrieval transparency

The crawler log now records the content kind (`html`, `pdf` or reader content) for successful fetches. This allows the source register to distinguish web pages from documents reliably.

## Version

`hostable_v67_scan_coverage_source_register`
