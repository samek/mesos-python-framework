#!/usr/bin/env python

#                                 _             __                                             _
#   _____  ____ _ _ __ ___  _ __ | | ___       / _|_ __ __ _ _ __ ___   _____      _____  _ __| | __
#  / _ \ \/ / _` | '_ ` _ \| '_ \| |/ _ \_____| |_| '__/ _` | '_ ` _ \ / _ \ \ /\ / / _ \| '__| |/ /
# |  __/>  < (_| | | | | | | |_) | |  __/_____|  _| | | (_| | | | | | |  __/\ V  V / (_) | |  |   <
#  \___/_/\_\__,_|_| |_| |_| .__/|_|\___|     |_| |_|  \__,_|_| |_| |_|\___| \_/\_/ \___/|_|  |_|\_\
#                          |_|
#

import Queue
import argparse
import sys
import os

import mesos
import mesos_pb2


class ExampleScheduler(mesos.Scheduler):
    """Example scheduler that launches tasks that don't do a whole lot.
    """

    TASK_CPU = 0.1
    TASK_MEM = 32

    def __init__(self, taskQueue):

        # Maintain a queue of the tasks to launch
        self.tasks = taskQueue

        self.terminal = 0
        self.total_tasks = taskQueue.qsize()

    def registered(self, driver, frameworkId, masterInfo):
        """
        Invoked when the scheduler successfully registers with a Mesos
        master. A unique ID (generated by the master) used for
        distinguishing this framework from others and MasterInfo
        with the ip and port of the current master are provided as arguments.
        """

        print >> sys.stderr, "Registered framework %s" % (frameworkId.value)

    def reregistered(self, driver, masterInfo):
        """
        Invoked when the scheduler re-registers with a newly elected Mesos master.
        This is only called when the scheduler has previously been registered.
        MasterInfo containing the updated information about the elected master
        is provided as an argument.
        """

        print >> sys.stderr, "Connected with master %s" % (masterInfo.ip)

    def disconnected(self, driver):
        """
        Invoked when the scheduler becomes "disconnected" from the master
        (e.g., the master fails and another is taking over).
        """

        print >> sys.stderr, "Disconnected from master"

    def resourceOffers(self, driver, offers):
        """
        Invoked when resources have been offered to this framework. A
        single offer will only contain resources from a single slave.

        Resources associated with an offer will not be re-offered to
        _this_ framework until either (a) this framework has rejected
        those resources (see SchedulerDriver::launchTasks) or (b) those
        resources have been rescinded (see Scheduler::offerRescinded).

        Note that resources may be concurrently offered to more than one
        framework at a time (depending on the allocator being used). In
        that case, the first framework to launch tasks using those
        resources will be able to use them while the other frameworks
        will have those resources rescinded (or if a framework has
        already launched tasks with those resources then those tasks will
        fail with a TASK_LOST status and a message saying as much).
        """

        print >> sys.stderr, "Received offers"

        if self.tasks.empty():
            return  # Skip as there are no tasks left to worry about

        # Loop over the offers and see if there's anything that looks good
        for offer in offers:
            offer_cpu = 0
            offer_mem = 0

            # Collect up the CPU and Memory resources from the offer
            for resource in offer.resources:
                if resource.name == "cpus":
                    offer_cpu = resource.scalar.value
                if resource.name == "mem":
                    offer_mem = resource.scalar.value

            tasks = []

            # Keep looking for tasks until any of the following critera are met
            #   - No more CPU left in the offer
            #   - No more Memory left in the offer
            #   - No more tasks left to launch
            while offer_mem >= self.TASK_MEM and offer_cpu >= self.TASK_CPU \
                and not self.tasks.empty(): \

                offer_cpu -= self.TASK_CPU
                offer_mem -= self.TASK_MEM

                # Pop a task off the queue
                executor_id, task_id = self.tasks.get()
                self.tasks.task_done()  # Mark it as done immediately

                print >> sys.stderr, "Queue task %d:%d" % (executor_id, task_id)
                tasks.append(self._buildTask(offer, executor_id, task_id))

            # If we have any tasks to launch, ask the driver to launch them.
            if tasks:
                driver.launchTasks(offer.id, tasks)

    def _buildTask(self, offer, executor_id, task_id):
        """
        Create a TaskInfo object for an offer, executor_id and task_id.
        """

        # Create the initial TaskInfo object
        task = mesos_pb2.TaskInfo()
        task.name = "Test Framework Task"
        task.task_id.value = "%d:%d" % (executor_id, task_id)
        task.slave_id.value = offer.slave_id.value

        # Configure the executor
        task.executor.executor_id.value = str(executor_id)
        task.executor.framework_id.value = offer.framework_id.value

        # Find the relative path to the executor.
        # NOTE: This will only work when the slave is running on the same machine
        # as this framework.
        executor_path = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "bin/executor"
        )
        task.executor.command.value = os.path.abspath(executor_path)

        # Add the task resource
        cpus = task.resources.add()
        cpus.name = "cpus"
        cpus.type = mesos_pb2.Value.SCALAR
        cpus.scalar.value = self.TASK_CPU

        mem = task.resources.add()
        mem.name = "mem"
        mem.type = mesos_pb2.Value.SCALAR
        mem.scalar.value = self.TASK_MEM

        return task

    def offerRescinded(self, driver, offerId):
        """
        Invoked when an offer is no longer valid (e.g., the slave was
        lost or another framework used resources in the offer). If for
        whatever reason an offer is never rescinded (e.g., dropped
        message, failing over framework, etc.), a framwork that attempts
        to launch tasks using an invalid offer will receive TASK_LOST
        status updats for those tasks (see Scheduler::resourceOffers).
        """

        print >> sys.stderr, "Offer rescinded %s" % (offerId.value)

    def statusUpdate(self, driver, taskStatus):
        """
        Invoked when the status of a task has changed (e.g., a slave is
        lost and so the task is lost, a task finishes and an executor
        sends a status update saying so, etc). Note that returning from
        this callback _acknowledges_ receipt of this status update! If
        for whatever reason the scheduler aborts during this callback (or
        the process exits) another status update will be delivered (note,
        however, that this is currently not true if the slave sending the
        status update is lost/fails during that time).
        """

        statuses = {
            mesos_pb2.TASK_STAGING: "STAGING",
            mesos_pb2.TASK_STARTING: "STARTING",
            mesos_pb2.TASK_RUNNING: "RUNNING",
            mesos_pb2.TASK_FINISHED: "FINISHED",
            mesos_pb2.TASK_FAILED: "FAILED",
            mesos_pb2.TASK_KILLED: "KILLED",
            mesos_pb2.TASK_LOST: "LOST",
        }

        print >> sys.stderr, "Received status update for task %s (%s)" % (
            taskStatus.task_id.value,
            statuses[taskStatus.state]
        )

        if taskStatus.state == mesos_pb2.TASK_FINISHED or \
            taskStatus.state == mesos_pb2.TASK_FAILED or \
            taskStatus.state == mesos_pb2.TASK_KILLED or \
            taskStatus.state == mesos_pb2.TASK_LOST: \

            # Mark this task as terminal
            self.terminal += 1

        if self.terminal == self.total_tasks:
            driver.stop()

    def frameworkMessage(self, driver, executorId, slaveId, data):
        """
        Invoked when an executor sends a message. These messages are best
        effort; do not expect a framework message to be retransmitted in
        any reliable fashion.
        """

        print >> sys.stderr, "Message from executor %s and slave %s: %s" % (
            executorId.value,
            slaveId.value,
            data
        )

    def slaveLost(self, driver, slaveId):
        """
        Invoked when a slave has been determined unreachable (e.g.,
        machine failure, network partition). Most frameworks will need to
        reschedule any tasks launched on this slave on a new slave.
        """

        print >> sys.stderr, "Slave %s has been lost. Y U DO DIS." % (slaveId.value)

    def executorLost(self, driver, executorId, slaveId, exitCode):
        """
        Invoked when an executor has exited/terminated. Note that any
        tasks running will have TASK_LOST status updates automagically
        generated.
        """

        print >> sys.stderr, "Executor %s has been lost on slave %s with exit code %d" % (
            executorId.value,
            slaveId.value,
            exitCode
        )

    def error(self, driver, message):
        """
        Invoked when there is an unrecoverable error in the scheduler or
        scheduler driver. The driver will be aborted BEFORE invoking this
        callback.
        """

        print >> sys.stderr, "There was an error: %s" % (message)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(prog="docker-launcher")
    parser.add_argument("-m", "--master", required=True, type=str,
                        help="IP/Port of mesos master")
    parser.add_argument("--num-tasks", default=1, type=int,
                        help="Number of tasks to launch per executor (default: 1)")
    parser.add_argument("--num-executors", default=1, type=int,
                        help="Number of executors to launch (default: 1)")

    args = parser.parse_args()

    # Create the queue of tasks
    tasks = Queue.Queue()
    for task in xrange(args.num_tasks):
        for executor in xrange(args.num_executors):
            tasks.put((executor, task))

    # Launch the mesos framework
    framework = mesos_pb2.FrameworkInfo()
    framework.user = ""  # Mesos can select the user
    framework.name = "Test Python Framework"

    driver = mesos.MesosSchedulerDriver(
        ExampleScheduler(tasks),
        framework,
        args.master
    )

    status = 0
    if driver.run() == mesos_pb2.DRIVER_STOPPED:
        status = 1

    driver.stop()
    exit(status)
