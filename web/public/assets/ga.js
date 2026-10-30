// GA4, one property for all of Sean's sites (monode infrastructure/ANALYTICS.md). Production hostname
// only: dev, localhost and the tailnet never load it. page_location drops the #fragment, which holds
// a shared cohort definition (#d=...).
if (location.hostname === "uccc-genomics.cancerdatasci.org") {
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { dataLayer.push(arguments); };
  gtag("js", new Date());
  gtag("config", "G-KLLV1GCF4E", {content_group: "uccc-genomics", page_location: location.origin + location.pathname + location.search});
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://www.googletagmanager.com/gtag/js?id=G-KLLV1GCF4E";
  document.head.appendChild(s);
}
