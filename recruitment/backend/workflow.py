"""Durable conversation turns; request resources never enter checkpoints."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import threading
from typing import Callable, TypedDict
from weakref import WeakValueDictionary

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt


class ConversationState(TypedDict):
    memory: dict
    event: dict
    result: dict


@dataclass
class TurnContext:
    handle: Callable


def process_turn(state: ConversationState,runtime: Runtime[TurnContext]):
    return runtime.context.handle(deepcopy(state.get('memory',{})),state['event'])


def await_input(state: ConversationState):
    event=interrupt({'pending_question':state.get('memory',{}).get('pending_question')})
    return {'event':event}


class ConversationWorkflow:
    def __init__(self,path):
        if str(path)!=':memory:':Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.connection=sqlite3.connect(str(path),check_same_thread=False,timeout=30)
        self.saver=SqliteSaver(self.connection)
        graph=StateGraph(ConversationState,context_schema=TurnContext)
        graph.add_node('turn',process_turn)
        graph.add_node('await_input',await_input)
        graph.add_edge(START,'turn')
        graph.add_edge('turn','await_input')
        graph.add_edge('await_input','turn')
        self.graph=graph.compile(checkpointer=self.saver)
        self.lock_guard=threading.Lock()
        self.locks=WeakValueDictionary()

    def peek(self,thread_id):
        return self.graph.get_state({'configurable':{'thread_id':thread_id}}).values or {}

    def run(self,thread_id,event,handle,initial_memory=None):
        # This process owns the local demo runner; shared multi-worker deployment
        # needs a database-backed per-thread lease before accepting concurrent turns.
        with self.lock_guard:
            lock=self.locks.get(thread_id)
            if lock is None:
                lock=threading.RLock();self.locks[thread_id]=lock
        with lock:
            config={'configurable':{'thread_id':thread_id}}
            snapshot=self.graph.get_state(config)
            context=TurnContext(handle)
            if snapshot.next and not snapshot.interrupts:
                self.graph.invoke(None,config,context=context,durability='sync')
                snapshot=self.graph.get_state(config)
            value=Command(resume=event) if snapshot.interrupts else {'memory':initial_memory or {},'event':event}
            return self.graph.invoke(value,config,context=context,durability='sync')

    def close(self):
        self.connection.close()
