export function estimateTokens(text: string): number {
  if (!text) return 0
  const chars = Array.from(text)
  const chineseChars = chars.filter((char) => /[\u4e00-\u9fff]/.test(char)).length
  const otherChars = chars.length - chineseChars
  return Math.max(1, Math.floor(chineseChars / 1.5 + otherChars / 4))
}

let tokenizerLoader: Promise<((text: string) => number) | null> | null = null

async function loadTokenizer(): Promise<((text: string) => number) | null> {
  if (tokenizerLoader) return tokenizerLoader
  tokenizerLoader = (async () => {
    try {
      const mod = await import('js-tiktoken')
      const getEncoding = (mod as { getEncoding?: (name: string) => { encode: (value: string) => number[] } }).getEncoding
      if (!getEncoding) return null
      const encoder = getEncoding('o200k_base')
      return (text: string) => encoder.encode(text).length
    } catch {
      return null
    }
  })()
  return tokenizerLoader
}

export async function countDraftTokens(text: string): Promise<number> {
  if (!text) return 0
  const tokenizer = await loadTokenizer()
  if (tokenizer) {
    try {
      return tokenizer(text)
    } catch {
      return estimateTokens(text)
    }
  }
  return estimateTokens(text)
}
