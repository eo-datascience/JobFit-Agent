// Reading a CV in the browser.
//
// The file is never uploaded. It is read with FileReader, parsed here, and the
// text is discarded when the tab closes. That is the whole privacy story, and
// it is worth saying plainly on the page rather than only in the code.
//
// Both parsers are loaded on demand, the first time someone picks a file, so
// visitors who only browse the market data never download them.

export const ACCEPTED = '.pdf,.docx,.txt,.md'

const MAX_BYTES = 8 * 1024 * 1024

export class ReadError extends Error {}

/** Below this, a file almost certainly produced no readable text at all. */
export const MIN_READABLE_CHARS = 200

async function readPdf(file: File): Promise<string> {
  // The legacy build, not the default one. The default targets browsers so
  // recent that it calls methods a year or two old, and a visitor on anything
  // slightly behind gets an unreadable error instead of their results. The
  // legacy build is the same patched version with those gaps filled in.
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  // Vite bundles the worker from the installed package rather than fetching it
  // from a CDN, which keeps the page working with no external requests.
  const worker = await import('pdfjs-dist/legacy/build/pdf.worker.mjs?url')
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default

  // A CV is an untrusted file from a stranger's machine, and neither of these
  // features is needed to read text out of one. Version 6 of this library
  // removed its use of eval altogether, which is what closed the advisory
  // about arbitrary code execution from a crafted PDF.
  const task = pdfjs.getDocument({
    data: new Uint8Array(await file.arrayBuffer()),
    disableAutoFetch: true,
    enableXfa: false,
  })
  const doc = await task.promise

  const pages: string[] = []
  for (let n = 1; n <= doc.numPages; n++) {
    const page = await doc.getPage(n)
    const content = await page.getTextContent()
    pages.push(
      content.items
        .map((item) => ('str' in item ? item.str : ''))
        .join(' '),
    )
  }
  await task.destroy()
  return pages.join('\n')
}

async function readDocx(file: File): Promise<string> {
  const mammoth = await import('mammoth/mammoth.browser.js')
  const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() })
  return result.value
}

/** Read a CV file and return its plain text. */
export async function readCv(file: File): Promise<string> {
  if (file.size > MAX_BYTES) {
    throw new ReadError('That file is larger than 8MB. A CV is usually well under 1MB.')
  }

  const name = file.name.toLowerCase()
  try {
    if (name.endsWith('.pdf')) return await readPdf(file)
    if (name.endsWith('.docx')) return await readDocx(file)
    if (name.endsWith('.txt') || name.endsWith('.md')) return await file.text()
  } catch (err) {
    throw new ReadError(
      `That file could not be read. ${err instanceof Error ? err.message : ''} ` +
      'If it is a scanned PDF the text is an image, so try a Word file or paste the text instead.',
    )
  }

  if (name.endsWith('.doc')) {
    throw new ReadError('Older .doc files cannot be read here. Save it as .docx or PDF first.')
  }
  throw new ReadError('Choose a PDF, a Word .docx, or a plain text file.')
}
