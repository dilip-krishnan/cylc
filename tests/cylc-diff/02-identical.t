#!/bin/bash
# THIS FILE IS PART OF THE CYLC SUITE ENGINE.
# Copyright (C) 2008-2017 NIWA
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#-------------------------------------------------------------------------------
# Test for "cylc diff" with identical suite definitions.
. "$(dirname "$0")/test_header"

set_test_number 3

init_suite "${TEST_NAME_BASE}-1" <<'__SUITE_RC__'
[scheduling]
    [[dependencies]]
        graph = foo => bar
[runtime]
    [[foo, bar]]
        script = true
__SUITE_RC__
SUITE_NAME1="${SUITE_NAME}"
init_suite "${TEST_NAME_BASE}-2" <<'__SUITE_RC__'
[scheduling]
    [[dependencies]]
        graph = foo => bar
[runtime]
    [[foo, bar]]
        script = true
__SUITE_RC__
SUITE_NAME2="${SUITE_NAME}"

run_ok "${TEST_NAME_BASE}" cylc diff "${SUITE_NAME1}" "${SUITE_NAME2}"
cmp_ok "${TEST_NAME_BASE}.stdout" <<__OUT__
Parsing ${SUITE_NAME1} (${TEST_DIR}/${SUITE_NAME1}/suite.rc)
Parsing ${SUITE_NAME2} (${TEST_DIR}/${SUITE_NAME2}/suite.rc)
Suite definitions ${SUITE_NAME1} and ${SUITE_NAME2} are identical
__OUT__
cmp_ok "${TEST_NAME_BASE}.stderr" <'/dev/null'

purge_suite "${SUITE_NAME1}"
purge_suite "${SUITE_NAME2}"
exit
