import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, listTagFamilies, type TagFamily } from "./api";
import { ConfirmModal } from "./ConfirmModal";
import { TagAddModal } from "./TagAddModal";
import { TagFamiliesAside, type FamilyFilter } from "./TagFamiliesAside";
import type { QueryDslAppend } from "./queryNavigation";
import { filterTagsByFamily, groupTagsByFamily, type TagRow } from "./tagGrouping";

type Tag = TagRow & {
  breach_date: string | null;
};

type Me = { roles: string[] };

export function TagsPage() {
  const navigate = useNavigate();
  const [tags, setTags] = useState<Tag[]>([]);
  const [families, setFamilies] = useState<TagFamily[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [familyFilter, setFamilyFilter] = useState<FamilyFilter>("all");
  const [err, setErr] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [pendingDeleteTagId, setPendingDeleteTagId] = useState<string | null>(null);
  const [removingTagId, setRemovingTagId] = useState<string | null>(null);

  const canWrite = me?.roles.some((r) => r === "admin" || r === "operator" || r === "manager") ?? false;
  const isAdmin = me?.roles.includes("admin") ?? false;

  const defaultFamily =
    familyFilter !== "all" && familyFilter !== "unassigned" ? familyFilter : "";

  async function loadPageData() {
    const [t, f, m] = await Promise.all([
      api<Tag[]>("/tags"),
      listTagFamilies(),
      api<Me>("/auth/me"),
    ]);
    setTags(t);
    setFamilies(f);
    setMe(m);
  }

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        await loadPageData();
        setErr(null);
      } catch (ex) {
        setErr(String(ex));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const counts = useMemo(() => {
    const byCode = new Map<string, number>();
    let unassigned = 0;
    for (const tag of tags) {
      if (!tag.family) {
        unassigned += 1;
        continue;
      }
      byCode.set(tag.family, (byCode.get(tag.family) ?? 0) + 1);
    }
    return { all: tags.length, unassigned, byCode };
  }, [tags]);

  const visibleTags = useMemo(
    () => filterTagsByFamily(tags, familyFilter),
    [tags, familyFilter],
  );

  const groupedTags = useMemo(() => {
    if (familyFilter !== "all") return null;
    return groupTagsByFamily(visibleTags);
  }, [familyFilter, visibleTags]);

  function goToQuery(append: QueryDslAppend) {
    navigate("/query", { state: { dslAppend: append } });
  }

  async function confirmRemoveTag() {
    if (!pendingDeleteTagId) return;
    setErr(null);
    setRemovingTagId(pendingDeleteTagId);
    try {
      await api(`/tags/${pendingDeleteTagId}`, { method: "DELETE" });
      setPendingDeleteTagId(null);
      await loadPageData();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setRemovingTagId(null);
    }
  }

  const familyQueryCode =
    familyFilter !== "all" && familyFilter !== "unassigned" ? familyFilter : null;

  return (
    <div className="tags-page">
      <header className="page-head">
        <div>
          <h1>Tags</h1>
          <p className="lead">Pick a family, then click a tag to open Query with <code>tag:name</code>.</p>
        </div>
        <div className="page-head__actions btn-row">
          <Link to="/query" className="secondary">
            Query
          </Link>
          {canWrite ? (
            <button type="button" onClick={() => setAddOpen(true)}>
              Add tag
            </button>
          ) : null}
        </div>
      </header>

      {err && !addOpen ? <p className="error">{err}</p> : null}
      {statusMsg ? <p className="hint">{statusMsg}</p> : null}

      <div className="tags-layout">
        <aside className="panel tags-aside">
          <h2 className="tags-aside__title">Families</h2>
          <TagFamiliesAside
            families={families}
            familyFilter={familyFilter}
            onSelectFamily={setFamilyFilter}
            counts={counts}
            canWrite={canWrite}
            onChanged={loadPageData}
            onError={setErr}
          />
        </aside>

        <section className="panel tags-main">
          {familyQueryCode ? (
            <div className="tags-main__family-action">
              <button
                type="button"
                className="secondary"
                onClick={() => goToQuery({ kind: "family", value: familyQueryCode })}
              >
                Query <code>tag.family:{familyQueryCode}</code>
              </button>
            </div>
          ) : null}

          {loading ? (
            <p className="muted">Loading…</p>
          ) : visibleTags.length === 0 ? (
            <p className="hint">{tags.length === 0 ? "No tags yet." : "No tags in this family."}</p>
          ) : familyFilter === "all" && groupedTags ? (
            <div className="tag-family-groups">
              {groupedTags.map((group) => (
                <section key={group.family ?? "__none__"} className="tag-family-group">
                  <h3 className="tag-family-group__title">{group.family ?? "No family"}</h3>
                  <TagChipList
                    items={group.items}
                    onApply={(name) => goToQuery({ kind: "tag", value: name })}
                    onRemove={isAdmin ? (id) => setPendingDeleteTagId(id) : undefined}
                  />
                </section>
              ))}
            </div>
          ) : (
            <TagChipList
              items={visibleTags}
              onApply={(name) => goToQuery({ kind: "tag", value: name })}
              onRemove={isAdmin ? (id) => setPendingDeleteTagId(id) : undefined}
            />
          )}
        </section>
      </div>

      {canWrite ? (
        <TagAddModal
          open={addOpen}
          onClose={() => setAddOpen(false)}
          families={families}
          defaultFamily={defaultFamily}
          onCreated={loadPageData}
          onBulkQueued={(msg) => {
            setStatusMsg(msg);
            setErr(null);
          }}
        />
      ) : null}

      <ConfirmModal
        open={pendingDeleteTagId !== null}
        title="Delete tag"
        message="Delete this tag?"
        confirmLabel="Delete"
        pending={removingTagId !== null}
        onConfirm={() => void confirmRemoveTag()}
        onCancel={() => {
          if (removingTagId) return;
          setPendingDeleteTagId(null);
        }}
      />
    </div>
  );
}

function TagChipList({
  items,
  onApply,
  onRemove,
}: {
  items: TagRow[];
  onApply: (name: string) => void;
  onRemove?: (id: string) => void;
}) {
  return (
    <ul className="tag-chips tag-chips--lg">
      {items.map((t) => (
        <li key={t.id} className="tag-chip-item tag-chip-item--lg">
          <button type="button" className="tag-chip tag-chip--lg" onClick={() => onApply(t.name)} title={`Query tag:${t.name}`}>
            <span className="tag-chip__label">{t.name}</span>
          </button>
          {onRemove ? (
            <button
              type="button"
              className="tag-chip__remove tag-chip__remove--lg secondary"
              aria-label={`Delete ${t.name}`}
              onClick={() => onRemove(t.id)}
            >
              ×
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
