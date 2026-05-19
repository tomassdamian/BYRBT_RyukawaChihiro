# -*- coding: utf-8 -*-
# @Author: LetMeFly (extended)
# @Description: leechersAndSeeders strategy — targets all free torrents,
#               ranked by leecher/seeder ratio for maximum upload gain.

from __future__ import annotations
import math
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _ratio_score(leechers: int, seeders: int) -> float:
    return leechers / (seeders + 1)

def _gb_to_bytes(gb: float) -> int:
    return int(gb * 1024 ** 3)

def _bytes_to_gb(b: int) -> float:
    return b / 1024 ** 3

class LeechersAndSeedersStrategy:
    def __init__(self, byrbt_client, bt_client, max_disk_gb: float, min_score: float = 0.5, save_path: Optional[str] = None) -> None:
        self.byrbt = byrbt_client
        self.bt = bt_client
        self.max_disk_bytes = _gb_to_bytes(max_disk_gb)
        self.min_score = min_score
        self.save_path = save_path

    def run(self) -> None:
        logger.info("[leechersAndSeeders] Refresh cycle started.")
        free_torrents: List[Dict[str, Any]] = self.byrbt.get_free_torrents()
        if not free_torrents:
            logger.info("[leechersAndSeeders] No free torrents found.")
            return

        for t in free_torrents:
            t["_score"] = _ratio_score(t["leechers"], t["seeders"])
        candidates = [t for t in free_torrents if t["_score"] >= self.min_score]
        candidates.sort(key=lambda t: t["_score"], reverse=True)

        active: List[Dict[str, Any]] = self.bt.get_torrents()
        site_ids_active = {t.get("site_id") for t in active if t.get("site_id")}

        for torrent in candidates:
            if torrent["id"] in site_ids_active:
                continue
            needed_bytes = torrent["size_bytes"]
            if not self._ensure_space(needed_bytes, active, candidates):
                continue
            self._download(torrent)
            active = self.bt.get_torrents()
            site_ids_active = {t.get("site_id") for t in active if t.get("site_id")}
        logger.info("[leechersAndSeeders] Refresh cycle complete.")

    def _current_usage_bytes(self, active: List[Dict[str, Any]]) -> int:
        return sum(t.get("size", 0) for t in active)

    def _ensure_space(self, needed_bytes: int, active: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> bool:
        free_bytes = self.max_disk_bytes - self._current_usage_bytes(active)
        if free_bytes >= needed_bytes:
            return True
        candidate_ids = {t["id"] for t in candidates}
        def eviction_score(active_torrent: Dict[str, Any]) -> float:
            site_id = active_torrent.get("site_id")
            if site_id and site_id not in candidate_ids:
                return -math.inf
            return active_torrent.get("_score", 0.0)
        eviction_order = sorted(active, key=eviction_score)
        for victim in eviction_order:
            if free_bytes >= needed_bytes:
                break
            size = victim.get("size", 0)
            self.bt.delete_torrent(victim["hash"], delete_files=True)
            free_bytes += size
            active = [t for t in active if t["hash"] != victim["hash"]]
        return free_bytes >= needed_bytes

    def _download(self, torrent: Dict[str, Any]) -> None:
        download_url = self.byrbt.get_download_url(torrent["id"])
        kwargs: Dict[str, Any] = {}
        if self.save_path:
            kwargs["savepath"] = self.save_path
        self.bt.add_torrent(download_url, site_id=torrent["id"], **kwargs)
