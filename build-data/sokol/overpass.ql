[out:json][timeout:60];
(
  way["highway"="raceway"](43.55,76.52,43.63,76.62);
  way["leisure"="track"]["sport"~"motor"](43.55,76.52,43.63,76.62);
  relation["highway"="raceway"](43.55,76.52,43.63,76.62);
);
out geom;
