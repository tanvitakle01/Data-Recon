import { twMerge } from "tailwind-merge";

/**
 * Tiny classnames helper. Accepts strings / arrays / falsy values and resolves
 * Tailwind conflicts via tailwind-merge. Avoids a hard dependency on clsx.
 */
export function cn(...inputs) {
  const flat = [];
  const walk = (x) => {
    if (!x) return;
    if (Array.isArray(x)) x.forEach(walk);
    else if (typeof x === "string") flat.push(x);
    else if (typeof x === "object") {
      for (const [k, v] of Object.entries(x)) if (v) flat.push(k);
    }
  };
  inputs.forEach(walk);
  return twMerge(flat.join(" "));
}
