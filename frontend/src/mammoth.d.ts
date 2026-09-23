// mammoth ships no types for its browser build, which is the one that works in
// a bundler without Node built ins. Only the function used here is declared.
declare module 'mammoth/mammoth.browser.js' {
  export function extractRawText(input: { arrayBuffer: ArrayBuffer }): Promise<{ value: string }>
}
