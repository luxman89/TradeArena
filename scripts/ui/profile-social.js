window.shareProfile = async function () {
  const status = document.getElementById("profile-status");
  try {
    if (navigator.share)
      await navigator.share({ title: document.title, url: location.href });
    else {
      await navigator.clipboard.writeText(location.href);
      status.textContent = "Profile link copied.";
    }
  } catch (error) {
    if (error.name !== "AbortError")
      status.textContent =
        "Sharing unavailable. Copy the address from your browser.";
  }
};

var _profileCreatorId = null;
var _isFollowing = false;

function _jwt() {
  try {
    return (
      localStorage.getItem("ta_token") ||
      sessionStorage.getItem("ta_token") ||
      ""
    );
  } catch {
    return "";
  }
}

window.loadFollowState = async function (creatorId) {
  _profileCreatorId = creatorId;

  // Always load follower/following counts (no auth required)
  try {
    var [fwRes, fgRes] = await Promise.all([
      fetch("/creator/" + encodeURIComponent(creatorId) + "/followers?limit=1"),
      fetch("/creator/" + encodeURIComponent(creatorId) + "/following?limit=1"),
    ]);
    if (fwRes.ok && fgRes.ok) {
      var fw = await fwRes.json();
      var fg = await fgRes.json();
      document.getElementById("follower-count").textContent = fw.total || 0;
      document.getElementById("following-count").textContent = fg.total || 0;
      document.getElementById("follow-counts").style.display = "";
    }
  } catch {
    /* counts are best-effort */
  }

  // Only show follow button if logged-in and viewing someone else's profile
  var token = _jwt();
  if (!token) return;
  try {
    var meRes = await fetch("/auth/me", {
      headers: { Authorization: "Bearer " + token },
    });
    if (!meRes.ok) return;
    var me = await meRes.json();
    if (me.creator_id === creatorId) return; // viewing own profile

    // Check if already following by checking followers list
    var checkRes = await fetch(
      "/creator/" + encodeURIComponent(creatorId) + "/followers?limit=100",
    );
    if (checkRes.ok) {
      var data = await checkRes.json();
      _isFollowing = data.followers.some(function (f) {
        return f.creator_id === me.creator_id;
      });
    }
    var btn = document.getElementById("follow-btn");
    btn.style.display = "";
    btn.textContent = _isFollowing ? "Following" : "Follow";
    if (_isFollowing) btn.classList.add("following");
  } catch {
    /* follow button is best-effort */
  }
};

window.toggleFollow = async function () {
  var token = _jwt();
  if (!token || !_profileCreatorId) return;
  var btn = document.getElementById("follow-btn");
  btn.disabled = true;
  try {
    var method = _isFollowing ? "DELETE" : "POST";
    var res = await fetch(
      "/creator/" + encodeURIComponent(_profileCreatorId) + "/follow",
      {
        method: method,
        headers: { Authorization: "Bearer " + token },
      },
    );
    if (!res.ok && res.status !== 409) throw new Error("unavailable");
    if (res.ok || res.status === 409) {
      _isFollowing = !_isFollowing;
      btn.textContent = _isFollowing ? "Following" : "Follow";
      btn.classList.toggle("following", _isFollowing);
      // Update count
      var countEl = document.getElementById("follower-count");
      var c = parseInt(countEl.textContent) || 0;
      countEl.textContent = _isFollowing ? c + 1 : Math.max(0, c - 1);
    }
  } catch {
    document.getElementById("profile-status").textContent =
      "Follow update failed. Please try again.";
  }
  btn.disabled = false;
};
