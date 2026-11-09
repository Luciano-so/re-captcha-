from app.portals import nfe_portal, receita_federal, sefaz_mt

PORTALS = {p.key: p for p in (nfe_portal.PORTAL, sefaz_mt.PORTAL, receita_federal.PORTAL)}
