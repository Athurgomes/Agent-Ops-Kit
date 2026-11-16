// Random password generator. Uses crypto.getRandomValues; nothing is stored or logged.
// The alphabet leaves out look-alike characters (0/O, 1/l/I) so it can be read aloud or retyped.
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";

export function generatePassword(length = 20): string {
  const out: string[] = [];
  const limit = 256 - (256 % ALPHABET.length); // rejection sampling: no modulo bias
  const buf = new Uint8Array(length * 2);
  while (out.length < length) {
    crypto.getRandomValues(buf);
    for (const b of buf) {
      if (b < limit && out.length < length) out.push(ALPHABET[b % ALPHABET.length]);
    }
  }
  return out.join("");
}
