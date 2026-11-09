import { BarChart3, Bot, ClipboardCheck, LayoutDashboard, ListChecks, ListTodo, Megaphone, Plug, Settings, UserCog, Users, type LucideIcon } from "lucide-react";

export interface NavTab {
  id: string;
  label: string;
  /** This sub-page lives at the section root, so its URL has no extra segment. */
  base?: boolean;
  /** Reachable by URL but not listed in the menu — linked to from inside the section instead. */
  hidden?: boolean;
}
export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  tabs?: NavTab[];
  /** Draw a rule above this entry, splitting the menu into act / investigate / configure. */
  dividerBefore?: boolean;
}

const seo: NavTab[] = [
  { id: "audit-and-pages", label: "Audit & pages" },
  { id: "search-performance", label: "Search performance" },
  { id: "page-performance", label: "Page performance" },
  { id: "backlinks", label: "Backlinks" },
  { id: "rankings", label: "Rankings" },
  { id: "keywords", label: "Keywords" },
  { id: "history", label: "Crawl history" },
];
const geo: NavTab[] = [
  { id: "visibility", label: "Visibility" },
  { id: "ai-traffic", label: "AI traffic" },
  { id: "answers", label: "Answers" },
  { id: "influencing-sources", label: "Influencing sources" },
  { id: "prompts", label: "Prompts" },
  { id: "runs", label: "Run History" },
];
const brand: NavTab[] = [
  { id: "mentions", label: "Mentions" },
  { id: "by-entity", label: "By entity" },
];
const competitors: NavTab[] = [
  { id: "competitors", label: "Competitors", base: true },
  { id: "watched-pages", label: "Watched pages" },
  { id: "keyword-gap", label: "Keyword gap" },
  // Reached from the "Changed last time" column on Watched pages.
  { id: "page-changes", label: "Page changes", hidden: true },
];

/** The whole left-hand menu. Sections with `tabs` render as collapsible sub-menus; there is no second grouping level. */
export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/plan", label: "Growth Plan", icon: ClipboardCheck },
  { to: "/results", label: "Results", icon: ListChecks },
  { to: "/geo", label: "GEO AI Visibility", icon: Bot, tabs: geo, dividerBefore: true },
  { to: "/seo", label: "SEO Performance", icon: BarChart3, tabs: seo },
  { to: "/brand", label: "Brand Monitoring", icon: Megaphone, tabs: brand },
  { to: "/competitors", label: "Competitors", icon: Users, tabs: competitors },
  { to: "/jobs", label: "Jobs", icon: ListTodo, dividerBefore: true },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/team", label: "Team", icon: UserCog },
  { to: "/settings", label: "Settings", icon: Settings },
];

// Each page reads its own tab ids from the same list the menu is built from, so the two cannot drift apart.
const ids = (tabs: NavTab[]) => tabs.map((t) => t.id);
export const SEO_TABS = ids(seo);
export const GEO_TABS = ids(geo);
export const BRAND_TABS = ids(brand);
export const COMPETITOR_TABS = ids(competitors);

/** Where a sub-page lives. A `base` tab sits at the section root rather than under a child segment. */
export const tabHref = (item: NavItem, tab: NavTab) => (tab.base ? item.to : `${item.to}/${tab.id}`);

/** The sub-page the menu should link to first. */
export const firstTab = (item: NavItem) => item.tabs!.find((t) => !t.hidden) ?? item.tabs![0];

/** Which tab of `item` the path is on, or null if the path is outside that section. */
export function sectionTab(pathname: string, item: NavItem): string | null {
  if (!item.tabs?.length) return null;
  if (pathname === item.to) return (item.tabs.find((t) => t.base) ?? item.tabs[0]).id;
  return pathname.startsWith(`${item.to}/`) ? pathname.slice(item.to.length + 1).split("/")[0] : null;
}
