import type { AdminArea } from "../../adminApi";

export type Row = AdminArea & { depth: number };

/** Flat list ordered as a tree (parents first, children indented by depth). */
export function orderTree(areas: AdminArea[]): Row[] {
  const kids = new Map<number | null, AdminArea[]>();
  for (const a of areas) kids.set(a.parent_id, [...(kids.get(a.parent_id) ?? []), a]);
  const out: Row[] = [];
  const walk = (parent: number | null, depth: number) => {
    for (const a of kids.get(parent) ?? []) {
      out.push({ ...a, depth });
      walk(a.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

/** Ids of an area and everything under it (an area cannot be moved under any of these). */
export function selfAndDescendants(areas: AdminArea[], id: number): Set<number> {
  const out = new Set<number>([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const a of areas) {
      if (a.parent_id !== null && out.has(a.parent_id) && !out.has(a.id)) {
        out.add(a.id);
        grew = true;
      }
    }
  }
  return out;
}

export const indent = (depth: number) => "— ".repeat(depth);
