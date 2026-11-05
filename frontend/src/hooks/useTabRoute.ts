import { useParams } from "react-router-dom";

/**
 * The active sub-page, read from the URL. The menu on the left does the navigating, so pages only read.
 * Example: useActiveTab(SEO_TABS, "audit-and-pages")
 */
export function useActiveTab(tabs: readonly string[], fallback: string): string {
  const { tab } = useParams();
  return tab && tabs.includes(tab) ? tab : fallback;
}
