---
name: routing_keyword_expansion
version: 1.0.0
kind: build
category: customer-support
platform: universal
description: Expand routing keywords for order tracking and refund intents.
author: autoagent
tags:
- routing
- optimization
dependencies: []
allowed_tools: []
supported_frameworks: []
required_approvals: []
eval_contract: {}
rollout_policy: gradual
provenance: ''
trust_level: unverified
triggers:
- failure_family: routing_error
  metric_name: routing_accuracy
  threshold: 0.8
  operator: lt
---

# Routing_Keyword_Expansion

## Description

Expand routing keywords for order tracking and refund intents.

## Mutations

### expand_orders_keywords
- **type**: append
- **target**: routing
- **description**: Append missing shipping and tracking keywords to the orders route.
- **template**: |
    add keywords discovered from failure samples

## Examples

### order_tracking_keyword_gap
- **surface**: routing
- **before**: keywords:
- order
- tracking
- **after**: keywords:
- order
- tracking
- package
- **improvement**: 0.08

## Eval Criteria

- metric: routing_accuracy
  target: 0.9
  operator: gte
  weight: 1.0

## Guardrails

- Never remove existing safety routing rules.

