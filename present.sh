#!/usr/bin/env bash
#
# Jump between the twelve stages.
#
#   ./present.sh list     every stage
#   ./present.sh 5        check out stage 5
#   ./present.sh next     next stage
#   ./present.sh prev     previous stage
#   ./present.sh main     back to main
#
# Refuses to switch over uncommitted edits. Add -f to throw them away.

set -euo pipefail
cd "$(dirname "$0")"

FORCE=0
[ "${2:-}" = "-f" ] && FORCE=1

# A stage's commit on main: "(stage N)" in the subject, stage 1 is the first commit.
# Not merged yet? Fall back to the stage_N branch.
sha_of() {
	local n=$1 sha
	if [ "$n" = 1 ]; then
		sha=$(git rev-list --max-parents=0 main)
	else
		sha=$(git log main --format=%H --grep="(stage $n)" -1 --fixed-strings)
	fi
	[ -z "$sha" ] && sha=$(git rev-parse --verify -q "stage_$n" || true)
	echo "$sha"
}

current() {  # the stage HEAD is on, or 0
	local head n
	head=$(git rev-parse HEAD)
	for n in $(seq 1 12); do
		[ "$(sha_of "$n")" = "$head" ] && { echo "$n"; return; }
	done
	echo 0
}

guard() {
	[ -z "$(git status --porcelain --untracked-files=no)" ] && return
	if [ "$FORCE" = 1 ]; then
		git checkout -- .
		return
	fi
	git status --short --untracked-files=no
	echo "uncommitted changes. git stash, or add -f to throw them away"
	exit 1
}

goto() {
	local n=$1 sha
	sha=$(sha_of "$n")
	[ -z "$sha" ] && { echo "no stage $n"; exit 1; }
	guard
	# present.sh lives on main only, so old stages would delete it. Put it back.
	local self
	self=$(mktemp)
	cp "$0" "$self"
	rm -f present.sh
	git -c advice.detachedHead=false checkout -q "$sha"
	[ -f present.sh ] || { cp "$self" present.sh; chmod +x present.sh; }
	rm -f "$self"
	echo
	git log -1 --format="stage $n  %h  %s" "$sha"
	git show --stat --format="" "$sha" | sed 's/^/  /'
	echo
}

case "${1:-list}" in
	list)
		for n in $(seq 1 12); do
			sha=$(sha_of "$n")
			if [ -n "$sha" ]; then
				git log -1 --format="$(printf '%2d' "$n")  %h  %s" "$sha"
			else
				printf '%2d  -        missing\n' "$n"
			fi
		done
		;;
	next|prev)
		n=$(current)
		[ "$n" = 0 ] && { echo "not on a stage. try: ./present.sh 1"; exit 1; }
		if [ "$1" = next ]; then goto $((n + 1)); else goto $((n - 1)); fi
		;;
	main)
		guard
		# main tracks present.sh, so the restored copy would be in the way
		[ -n "$(git ls-files present.sh)" ] || rm -f present.sh
		git checkout -q main
		echo "back on main"
		;;
	*[!0-9]*|"")
		sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
		;;
	*)
		goto "$1"
		;;
esac
