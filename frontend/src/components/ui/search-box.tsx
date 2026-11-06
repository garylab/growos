import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  value: string;
  onSearch: (value: string) => void;
  placeholder?: string;
  className?: string;
}

/** A filter box that does NOT search while you type. The draft is held locally and committed to the parent
 *  only when the Search button is pressed or Enter is hit, so large tables are not re-filtered on every
 *  keystroke. A clear (×) button empties the box and resets the committed term in one click. Keep the parent
 *  `value` as the committed term; the box re-syncs to it if it changes elsewhere. */
export function SearchBox({ value, onSearch, placeholder, className }: Props) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  const submit = () => onSearch(draft.trim());
  const clear = () => { setDraft(""); onSearch(""); };
  return (
    <div className="flex gap-1">
      <div className={cn("relative", className)}>
        <Input
          className="w-full pr-8"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
        />
        {draft && (
          <button
            type="button"
            aria-label="Clear search"
            title="Clear"
            onClick={clear}
            className="absolute inset-y-0 right-0 flex items-center px-2.5 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <Button type="button" variant="outline" size="icon" aria-label="Search" title="Search" onClick={submit}>
        <Search className="h-4 w-4" />
      </Button>
    </div>
  );
}
