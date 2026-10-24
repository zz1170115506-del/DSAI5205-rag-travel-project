import test from 'node:test';
import assert from 'node:assert/strict';
import {PLAN_KEY, savePlan, readSavedPlan, clearPlan} from '../static/plan-storage.mjs';
const place = {id:'peak',tags:['拍照'],summary:'山顶资料',lat:22.27,lon:114.15};
const input = {days:1,region:'全部',pace:'轻松',rain:false,public_only:false,interests:['拍照'],must_visit:['peak']};
const plan = {days:[{stops:[{place,start:'17:00',end:'18:00'}],legs:[],end:'18:00'}],warnings:['非实时'],algorithm:'分组',trace:[{steps:['initialize']}]};
function storage() { const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}; }
function fixture() { const s=storage();savePlan(s,'v1',plan,input);return s; }
test('valid draft restores and clear removes both cache formats',()=>{const s=fixture();s.setItem('hkslow-plan-v1','legacy');assert.equal(readSavedPlan(s,'v1',[place],['拍照']).input.days,1);clearPlan(s);assert.equal(s.getItem(PLAN_KEY),null);assert.equal(s.getItem('hkslow-plan-v1'),null);});
test('changed knowledge version and removed place reject old draft',()=>{const s=fixture();assert.equal(readSavedPlan(s,'v2',[place],['拍照']),null);assert.equal(readSavedPlan(s,'v1',[],['拍照']),null);});
test('malformed and incomplete storage never breaks startup',()=>{const s=storage();for(const value of ['{','null','{}','{"schema":2}']){s.setItem(PLAN_KEY,value);assert.equal(readSavedPlan(s,'v1',[place],['拍照']),null);}});
test('invalid saved inputs, missing legs and inconsistent times are rejected',()=>{for(const mutate of [s=>s.input.interests=null,s=>s.input.days=99,s=>s.plan.days[0].legs=null,s=>s.plan.days[0].stops[0].end='16:00',s=>s.input.must_visit=['missing']]){const s=fixture();const v=JSON.parse(s.getItem(PLAN_KEY));mutate(v);s.setItem(PLAN_KEY,JSON.stringify(v));assert.equal(readSavedPlan(s,'v1',[place],['拍照']),null);}});
test('disabled browser storage falls back to current-page operation',()=>{const blocked={getItem(){throw Error('blocked')},setItem(){throw Error('quota')},removeItem(){throw Error('blocked')}};assert.equal(readSavedPlan(blocked,'v1',[place],['拍照']),null);assert.equal(savePlan(blocked,'v1',plan,input),false);assert.doesNotThrow(()=>clearPlan(blocked));});
