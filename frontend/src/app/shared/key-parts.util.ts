/**
 * Split a technical key (a permission such as `application.force_status`) after each
 * "." and "_", so a template can put a `<wbr>` between the parts. The key then breaks
 * only at those boundaries, never inside a word.
 */
export function keyParts(key: string): string[] {
  return key.split(/(?<=[._])/);
}
