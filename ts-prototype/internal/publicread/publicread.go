// Package publicread is the static, read-only public side of the log (C2SP tlog-tiles resources): GET/HEAD of the checkpoint, hash tiles and
// entry bundles ONLY. Everything else under the storage directory (tree-state database, lock files, anything not matching) is a 404.
package publicread

import (
	"net/http"
	"os"
	"path/filepath"
	"regexp"
)

var allowed = regexp.MustCompile(`^/(checkpoint|tile/(entries|[0-9]{1,2})(/x[0-9]{3})*/[0-9]{3}(\.p/[0-9]{1,3})?)$`)

func Handler(root string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		p := r.URL.Path
		if !allowed.MatchString(p) {
			http.NotFound(w, r)
			return
		}
		fp := filepath.Join(root, filepath.FromSlash(p))
		st, err := os.Lstat(fp)
		if err != nil || !st.Mode().IsRegular() {
			http.NotFound(w, r)
			return
		}
		if p == "/checkpoint" {
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			w.Header().Set("Cache-Control", "no-cache")
		} else {
			w.Header().Set("Content-Type", "application/octet-stream")
		}
		http.ServeFile(w, r, fp)
	})
}
