#!/usr/bin/env python

#C: THIS FILE IS PART OF THE CYLC FORECAST SUITE METASCHEDULER.
#C: Copyright (C) 2008-2012 Hilary Oliver, NIWA
#C:
#C: This program is free software: you can redistribute it and/or modify
#C: it under the terms of the GNU General Public License as published by
#C: the Free Software Foundation, either version 3 of the License, or
#C: (at your option) any later version.
#C:
#C: This program is distributed in the hope that it will be useful,
#C: but WITHOUT ANY WARRANTY; without even the implied warranty of
#C: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#C: GNU General Public License for more details.
#C:
#C: You should have received a copy of the GNU General Public License
#C: along with this program.  If not, see <http://www.gnu.org/licenses/>.

# THIS MODULE HANDLES DYNAMIC DEFINITION OF TASK PROXY CLASSES according
# to information parsed from the suite.rc file via config.py. It could
# probably do with some refactoring to make it more transparent ...

# TO DO : ONEOFF FOLLOWON TASKS: still needed but can now be identified
# automatically from the dependency graph?

# NOTE on conditional and non-conditional triggers: all plain triggers
# (for a single task) are held in a single prerequisite object; but one
# such object is held for each conditional trigger. This has
# implications for global detection of duplicated prerequisites
# (detection is currently disabled).

import sys, re
from OrderedDict import OrderedDict
from copy import deepcopy

from prerequisites.prerequisites_fuzzy import fuzzy_prerequisites
from prerequisites.prerequisites_loose import loose_prerequisites
from prerequisites.prerequisites import prerequisites
from prerequisites.plain_prerequisites import plain_prerequisites
from prerequisites.conditionals import conditional_prerequisites
from task_output_logs import logfiles
from outputs import outputs
from cycle_time import ct, at
from cycling import container

class Error( Exception ):
    """base class for exceptions in this module."""
    pass

class DefinitionError( Error ):
    """
    Exception raise for errors in taskdef initialization.
    """
    def __init__( self, msg ):
        self.msg = msg
    def __str__( self ):
        return repr( self.msg )

class taskdef(object):
    def __init__( self, name ):
        if re.search( '[^0-9a-zA-Z_\.]', name ):
            # dot for namespace syntax (NOT USED).
            # regex [\w] allows spaces.
            raise DefinitionError, "ERROR: Illegal task name: " + name

        self.name = name
        self.type = 'free'
        self.job_submit_method = None
        self.job_submission_shell = None
        self.job_submit_command_template = None
        self.job_submit_log_directory = None
        self.job_submit_share_directory = None
        self.job_submit_work_directory = None
        self.manual_messaging = False
        self.modifiers = []
        self.asyncid_pattern = None
        self.cycling = False

        self.remote_host = None
        self.owner = None
        self.remote_shell_template = None
        self.remote_cylc_directory = None
        self.remote_suite_directory = None
        self.remote_log_directory = None

        self.hook_script = None
        self.hook_events = []
        self.submission_timeout = None
        self.execution_timeout = None
        self.reset_timer = None

        self.intercycle = False
        self.cyclers = []
        self.logfiles = []
        self.description = ['Task description has not been completed' ]

        self.follow_on_task = None

        self.clocktriggered_offset = None

        # triggers[0,6] = [ A, B:1, C(T-6), ... ]
        self.triggers = OrderedDict()
        # cond[6,18] = [ '(A & B)|C', 'C | D | E', ... ]
        self.cond_triggers = OrderedDict()

        self.outputs = [] # list of explicit internal outputs; change to
                          # OrderedDict() if need to vary per cycle.

        self.loose_prerequisites = [] # asynchronous tasks

        self.command = None
        self.retry_delays = []
        self.precommand = None
        self.postcommand = None
        self.initial_scripting = None
        self.ssh_messaging = False

        self.environment = OrderedDict()  # var = value
        self.directives  = OrderedDict()  # var = value

        self.namespace_hierarchy = []

    def add_trigger( self, trigger, cycler ):
        if cycler not in self.triggers:
            self.triggers[ cycler ] = []
        self.triggers[cycler].append(trigger)

    def add_conditional_trigger( self, triggers, exp, cycler ):
        if cycler not in self.cond_triggers:
            self.cond_triggers[ cycler ] = []
        self.cond_triggers[ cycler ].append( [triggers,exp] )

    def add_to_valid_cycles( self, cyclr ):
            if len( self.cyclers ) == 0:
                self.cyclers = [cyclr]
            else:
                self.cyclers.append( cyclr )

    def time_trans( self, strng, hours=False ):
        # Time unit translation.
        # THIS IS NOT CURRENTLY USED, but may be useful in the future.
        # translate a time of the form:
        #  x sec, y min, z hr
        # into float MINUTES or HOURS,

        if not re.search( '^\s*(.*)\s*min\s*$', strng ) and \
            not re.search( '^\s*(.*)\s*sec\s*$', strng ) and \
            not re.search( '^\s*(.*)\s*hr\s*$', strng ):
                print >> sys.stderr, "ERROR: missing time unit on " + strng
                sys.exit(1)

        m = re.search( '^\s*(.*)\s*min\s*$', strng )
        if m:
            [ mins ] = m.groups()
            if hours:
                return str( float( mins / 60.0 ) )
            else:
                return str( float(mins) )

        m = re.search( '^\s*(.*)\s*sec\s*$', strng )
        if m:
            [ secs ] = m.groups()
            if hours:
                return str( float(secs)/3600.0 )
            else:
                return str( float(secs)/60.0 )

        m = re.search( '^\s*(.*)\s*hr\s*$', strng )
        if m:
            [ hrs ] = m.groups()
            if hours:
                #return str( float(hrs) )
                return float(hrs)
            else:
                #return str( float(hrs)*60.0 )
                return float(hrs)*60.0

    def get_task_class( self ):
        # return a task proxy class definition, to be used for
        # instantiating objects of this particular task class.
        base_types = []
        for foo in self.modifiers + [self.type]:
            # __import__() keyword args were introduced in Python 2.5
            #mod = __import__( 'cylc.task_types.' + foo, fromlist=[foo] )
            mod = __import__( 'cylc.task_types.' + foo, globals(), locals(), [foo] )
            base_types.append( getattr( mod, foo ) )

        tclass = type( self.name, tuple( base_types), dict())
        tclass.name = self.name        # TO DO: NOT NEEDED, USED class.__name__
        tclass.instance_count = 0
        tclass.upward_instance_count = 0
        tclass.description = self.description

        tclass.elapsed_times = []
        tclass.mean_total_elapsed_time = None

        tclass.hook_script = self.hook_script
        tclass.hook_events = self.hook_events
        tclass.submission_timeout = self.submission_timeout
        tclass.execution_timeout  = self.execution_timeout
        tclass.reset_timer =self.reset_timer

        tclass.remote_host = self.remote_host
        tclass.owner = self.owner
        tclass.remote_shell_template = self.remote_shell_template
        tclass.remote_cylc_directory = self.remote_cylc_directory
        tclass.remote_suite_directory = self.remote_suite_directory
        tclass.remote_log_directory = self.remote_log_directory

        tclass.job_submit_method = self.job_submit_method
        tclass.job_submission_shell = self.job_submission_shell
        tclass.job_submit_command_template = self.job_submit_command_template
        tclass.job_submit_log_directory = self.job_submit_log_directory
        tclass.job_submit_share_directory = self.job_submit_share_directory
        tclass.job_submit_work_directory = self.job_submit_work_directory
        tclass.manual_messaging = self.manual_messaging

        tclass.intercycle = self.intercycle
        tclass.follow_on = self.follow_on_task

        tclass.namespace_hierarchy = self.namespace_hierarchy

        def tclass_add_prerequisites( sself, startup, cycler, tag  ):

            # NOTE: Task objects hold all triggers defined for the task
            # in all cycling graph sections in this data structure:
            #     self.triggers[cycler] = [list of triggers for this cycler]
            # The list of triggers associated with cyclerX will only be
            # used by a particular task if the task's cycle time is a
            # valid member of cyclerX's sequence of cycle times.

            # 1) non-conditional triggers
            pp = plain_prerequisites( sself.id )
            sp = plain_prerequisites( sself.id )
            lp = loose_prerequisites( sself.id )
            for cyc in self.triggers:
                for trig in self.triggers[ cyc ]:
                    if trig.startup and not startup:
                            continue
                    if trig.cycling and not cyc.valid( ct(sself.tag) ):
                        # This trigger is not used in current cycle.
                        # (see NOTE just above)
                        ##DEBUGGING:
                        ##print >> sys.stderr, sself.name + ': this trigger not used for', sself.tag + ':'
                        ##print >> sys.stderr, ' ', trig.get(sself.tag, cyc)
                        continue
                    # NOTE that if we need to check validity of async
                    # tags, async tasks can appear in cycling sections
                    # in which case cyc.valid( at(sself.tag)) will fail.
                    if trig.async_repeating:
                        lp.add( trig.get( tag, cycler ))
                    else:
                        if trig.suicide:
                            sp.add( trig.get( tag, cycler ))
                        else:
                            pp.add( trig.get( tag, cycler ))
            sself.prerequisites.add_requisites( pp )
            sself.prerequisites.add_requisites( lp )
            sself.suicide_prerequisites.add_requisites( sp )

            # 2) conditional triggers
            for cyc in self.cond_triggers.keys():
                for ctrig, exp in self.cond_triggers[ cyc ]:
                    foo = ctrig.keys()[0]
                    if ctrig[foo].startup and not startup:
                        continue
                    if ctrig[foo].cycling and not cyc.valid( ct(sself.tag)):
                        # This trigger is not valid for current cycle.
                        # (see NOTE just above)
                        ##DEBUGGING:
                        ##print >> sys.stderr, sself.name + ': this trigger not used for', sself.tag + ':'
                        ##print >> sys.stderr, ' ', trig.get(sself.tag, cyc)
                        continue
                    # NOTE that if we need to check validity of async
                    # tags, async tasks can appear in cycling sections
                    # in which case cyc.valid( at(sself.tag)) will fail.
                    cp = conditional_prerequisites( sself.id )
                    for label in ctrig:
                        trig = ctrig[label]
                        cp.add( trig.get( tag, cycler ), label )
                    cp.set_condition( exp )
                    if ctrig[foo].suicide:
                        sself.suicide_prerequisites.add_requisites( cp )
                    else:
                        sself.prerequisites.add_requisites( cp )

        tclass.add_prerequisites = tclass_add_prerequisites

        # class init function
        def tclass_init( sself, start_tag, initial_state, stop_c_time=None, startup=False ):

            sself.cycon = container.cycon( self.cyclers )
            if self.cycling: # and startup:
                # adjust only needed at start-up but it does not hurt to
                # do it every time as after the first adjust we're already
                # on-cycle.
                sself.tag = sself.cycon.initial_adjust_up( start_tag )
            else:
                sself.tag = start_tag

            sself.c_time = sself.tag

            sself.id = sself.name + '%' + sself.tag

            sself.asyncid_pattern = self.asyncid_pattern

            sself.initial_scripting = self.initial_scripting
            sself.ssh_messaging = self.ssh_messaging

            sself.command = self.command

            # deepcopy retry delays: the deque gets pop()'ed in the task
            # proxy objects, which is no good if all instances of the
            # same task class reference the original deque!
            sself.retry_delays = deepcopy(self.retry_delays)

            sself.precommand = self.precommand
            sself.postcommand = self.postcommand

            if 'clocktriggered' in self.modifiers:
                sself.real_time_delay =  float( self.clocktriggered_offset )

            # prerequisites
            sself.prerequisites = prerequisites()
            sself.suicide_prerequisites = prerequisites()
            sself.add_prerequisites( startup, sself.cycon, sself.tag )

            sself.logfiles = logfiles()
            for lfile in self.logfiles:
                sself.logfiles.add_path( lfile )

            # outputs
            sself.outputs = outputs( sself.id )
            for outp in self.outputs:
                msg = outp.get( sself.tag )
                if not sself.outputs.exists( msg ):
                    sself.outputs.add( msg )
            sself.outputs.register()

            sself.env_vars = OrderedDict()
            for var in self.environment:
                val = self.environment[ var ]
                sself.env_vars[ var ] = val

            sself.directives = OrderedDict()
            for var in self.directives:
                val = self.directives[ var ]
                sself.directives[ var ] = val

            if 'catchup_clocktriggered' in self.modifiers:
                catchup_clocktriggered.__init__( sself )

            if stop_c_time:
                # cycling tasks with a final cycle time set
                super( sself.__class__, sself ).__init__( initial_state, stop_c_time )
            else:
                # TO DO: TEMPORARY HACK FOR ASYNC
                sself.stop_c_time = '99991231230000'
                super( sself.__class__, sself ).__init__( initial_state )

        tclass.__init__ = tclass_init

        return tclass
