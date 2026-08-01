#!/bin/bash
set -e
cd /root/joao/WinZapp_Python

echo "=== INICIANDO VARREDURA FORENSE EM LOTE ==="

# 1. Garantir working tree limpa
git status --porcelain | grep -q . && git stash --include-untracked || true

MAIN_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$MAIN_BRANCH" = "HEAD" ]; then MAIN_BRANCH="main"; fi

# Arquivos temporários para armazenar hashes
ALL_COMMITS_FILE=$(mktemp)
ALL_BLOBS_FILE=$(mktemp)
ACTIVE_COMMITS_FILE=$(mktemp)

cleanup() {
    rm -f "$ALL_COMMITS_FILE" "$ALL_BLOBS_FILE" "$ACTIVE_COMMITS_FILE"
}
trap cleanup EXIT

echo "[1/5] Extraindo hashes em lote de todas as fontes..."

# A. fsck lost-found
git fsck --lost-found --full --unreachable 2>&1 | awk '/commit/ {print $NF}' >> "$ALL_COMMITS_FILE" || true
git fsck --lost-found --full --unreachable 2>&1 | awk '/blob/ {print $NF}' >> "$ALL_BLOBS_FILE" || true

# B. Reflogs
git reflog show --all --format="%H" >> "$ALL_COMMITS_FILE" || true
git log --graft --all --format="%H" 2>/dev/null >> "$ALL_COMMITS_FILE" || true

# C. Git logs (arquivos de log)
if [ -d .git/logs ]; then
    grep -Eo '[0-9a-f]{40}' .git/logs/* -r 2>/dev/null | cut -d: -f2 | grep -v '^0000000000000000000000000000000000000000$' >> "$ALL_COMMITS_FILE" || true
fi

# D. Operações interrompidas (MERGE_HEAD, CHERRY_PICK_HEAD, etc.)
for head in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_HEAD ORIG_HEAD FETCH_HEAD; do
    if [ -f ".git/$head" ]; then
        grep -Eo '[0-9a-f]{40}' ".git/$head" >> "$ALL_COMMITS_FILE" || true
    fi
done
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    grep -Eo '[0-9a-f]{40}' .git/rebase-* -r 2>/dev/null | cut -d: -f2 >> "$ALL_COMMITS_FILE" || true
fi

# E. Stashes
git stash list --format="%H" >> "$ALL_COMMITS_FILE" || true

# F. Fast cat-file batch para filtrar apenas o que é commit e blob de fato
echo "[2/5] Filtrando e validando tipos de objetos em lote..."

SORTED_COMMITS=$(mktemp)
SORTED_BLOBS=$(mktemp)

cat "$ALL_COMMITS_FILE" | grep -E '^[0-9a-f]{40}$' | sort -u | git cat-file --batch-check='%(objectname) %(objecttype)' 2>/dev/null | awk '$2=="commit" {print $1}' > "$SORTED_COMMITS" || true
cat "$ALL_BLOBS_FILE" "$ALL_COMMITS_FILE" | grep -E '^[0-9a-f]{40}$' | sort -u | git cat-file --batch-check='%(objectname) %(objecttype)' 2>/dev/null | awk '$2=="blob" {print $1}' > "$SORTED_BLOBS" || true

# Obter commits alcançáveis pelas branches ativas para isolar apenas os órfãos
git rev-list --all >> "$ACTIVE_COMMITS_FILE" || true

ORPHAN_COMMITS=$(mktemp)
comm -23 <(sort -u "$SORTED_COMMITS") <(sort -u "$ACTIVE_COMMITS_FILE") > "$ORPHAN_COMMITS"

NUM_COMMITS=$(wc -l < "$ORPHAN_COMMITS")
NUM_BLOBS=$(wc -l < "$SORTED_BLOBS")

echo "Commits Órfãos Encontrados: $NUM_COMMITS"
echo "Blobs Encontrados: $NUM_BLOBS"

echo "[3/5] Criando branches em lote para commits órfãos..."
while read -r sha; do
    if [ -n "$sha" ]; then
        short_sha=${sha:0:8}
        branch_name="recuperado/commit-${short_sha}"
        if ! git rev-parse --verify "refs/heads/$branch_name" >/dev/null 2>&1; then
            git branch "$branch_name" "$sha" 2>/dev/null || true
        fi
    fi
done < "$ORPHAN_COMMITS"

echo "[4/5] Criando branches em lote para blobs soltos..."
mkdir -p recovered_blobs
while read -r sha; do
    if [ -n "$sha" ]; then
        short_sha=${sha:0:8}
        branch_name="recuperado/blob-${short_sha}"
        if ! git rev-parse --verify "refs/heads/$branch_name" >/dev/null 2>&1; then
            git checkout -b "$branch_name" "$MAIN_BRANCH" >/dev/null 2>&1
            file_path="recovered_blobs/blob_${short_sha}.bin"
            git cat-file -p "$sha" > "$file_path" 2>/dev/null
            git add "$file_path"
            git commit -m "Recuperação automática de blob solto $sha" >/dev/null 2>&1 || true
        fi
    fi
done < "$SORTED_BLOBS"

git checkout "$MAIN_BRANCH" >/dev/null 2>&1

echo "[5/5] EXECUTANDO PUSH EM LOTE ÚNICO DE TODAS AS BRANCHES 'recuperado/*'..."
git push origin 'refs/heads/recuperado/*'

echo "=== PROCESSO FORENSE CONCLUÍDO COM SUCESSO EM LOTE ==="
