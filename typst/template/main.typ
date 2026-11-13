// Entry point of one render job. The service writes doc.json next to it.
#import "tpl/protocol.typ": protocol
#import "tpl/plan.typ": plan
#let doc = json("doc.json")
#if doc.at("layout", default: "protocol") == "plan" { plan(doc) } else { protocol(doc) }
