"""
Proxy class for profiling Python objects. 

This provides a class named ProfilingProxy, which wraps an existing class,
instrumenting its method calls (and other method calls originating from them)
and collecting debugging statistics.  It may be used to wrap multiple classes,
and all instances of a class share the same profiling data.

The basic usage is like:


Author: Andrew Bulhak  (http://dev.null.org/acb/)
Copyright 2008 The pH Group
This code is free software, licensed under the GNU General Public License

class Spam:
   def baked_beans(self):
       ....

   def eggs(self):
       ....


# create some objects...
spam1 = ProfilingProxy(Spam(...))
spam2 = ProfilingProxy(Spam(...))

# ...and do things with them

spam1.eggs()
spam2.baked_beans()

# now get the profiling data; either object will do, as both share
# the same profiling data
profile = spam1._profiledata()

# print a flat list of functions and call times
profile.dumpflat()

# print a tree view
profile.dumptree()

"""

__version__ = "1.0"
__author__ = "Andrew C. Bulhak"
__copyright__ = "(C) 2008 The pH Group. GNU GPL 2."

import new
from types import MethodType
import time

# this should probably be a class
def _updateTSEntry(tse, delta, count, subcalls):
    """update a timestack entry, which represents the profile data for a 
       function and consists of a list of the form [total time, breakdown] 
       with breakdown being a dict of similar lists for functions called
       from this function."""
    tse[0] += delta
    tse[1] += count
    for (k,v) in subcalls.iteritems():
        tse[2].setdefault(k,[0.0, 0, {}])
        _updateTSEntry(tse[2][k], v[0], v[1], v[2])




class ClassProfileData(object):
    """A class keeping profile data on a specific class and its instances.
    """

    def __init__(self, classname):
        self.classname = classname 
        self.reset()

    def reset(self):
        """
        Reset the statistics
        """
        self.stack = []    # stack of nested method calls within this thread
        self.flat_times = {} # method name -> [ time,... ]; unnested call times
        # timestack is a stack of namespaces, with each one mapping method
        # names to a call-time record for that frame, consisting of 
        # [ total time, number of calls, { subordinate calls } ]
        # where subordinate calls is a namespace of methods called from
        # this method, with similar data; the key None therein refers to time
        # spent in the method itself.
        self.timestack = [ {} ] 

    def _push(self, name):
        "Start a function call"
        self.stack.append(name)
        self.timestack.append({})

    def _pop_and_log(self, delta):
        "End a function call"
        name = self.stack.pop()
        subcalls = self.timestack.pop()
        self.flat_times.setdefault(name,[]).append(delta)
        # synthesise a call for none of the above, i.e., the function body 
        subtotal = sum([v[0] for (k,v) in subcalls.iteritems() if k is not None])
        subcalls[None] = [ delta-subtotal, 1, {} ]
        self.timestack[-1].setdefault(name, [0.0, 0, {}])
        _updateTSEntry(self.timestack[-1][name], delta, 1, subcalls)

    def getFlatStats(self):
        """
        Return the collected statistics in flat mode, i.e., as a flat list
        of methods and how much time they took.  This method is a generator
        which returns a list of dictionaries with the keys 
        'method', 'calls', 'avgtime' and 'totaltime'
        """
        keys = self.flat_times.keys()
        keys.sort()

        #print "%-40s %-3s %-5s %-6s"%("Method", "Calls", "Avg.", "Total")
        for k in keys:
            ts = self.flat_times[k]
            #print ts
            tot = sum(ts)
            count = len(ts)
            avg = tot/count
            #print "%-40s %4d %3.2f %5.1f"%(k, count, avg, tot)
            yield dict(
                method = k,
                calls = count,
                totaltime = tot,
                avgtime = avg
            )

    def dumpflat(self):
        """
        Dump the collected statistics in flat mode, i.e., as a flat list
        of methods and how much time they took.
        """

        print "%-40s %-3s %-5s %-6s"%("Method", "Calls", "Avg.", "Total")
        for line in self.getFlatStats():
            print "%(method)-40s %(calls)4d %(avgtime)3.2f %(totaltime)5.1f"%line

    def getTreeStats(self, tree=None, level=0):
        """
        A generator that yields the calling time statistics, in the form of 
        a hierarchical tree, flattened out into a sequence. Each entry is 
        represented as a dictionary, with the fields:
          - level : the level (number of levels from the root) in the tree 
          - method : the name of the method called
          - time : the total time of the method call
          - calls : the number of method calls
          - percent : the percentage of the caller's time (including its
                      own body) that was spent in this method.
        """
        tree = tree or self.timestack[0]
        totaltime = sum([v[0] for v in tree.values()])
        methods = tree.keys()
        methods.sort(key=lambda k:tree[k][0], reverse=True)
        for method in methods:
            time,calls,sub = tree[method]
            percent = time/totaltime*100.0
            method = method or '(body)'
            yield dict(
                level = level,
                method = method,
                time = time,
                calls = calls,
                percent = percent
            )
            if len(sub)>1:
                for i in self.getTreeStats(sub, level+1):
                    yield i

    def dumptree(self):
        """
        Dump the statistics in a tree representation
        """
        print "Method                                   Time   #   %"
        for d in self.getTreeStats():
            d['lspace'] = '  '*d['level']
            d['rspace'] = '  '*(10-d['level'])
            print "%(lspace)s%(method)-20s%(rspace)s %(time)3.2f %(calls)3d  %(percent)2.1f%%"%d


class ProfilingProxy(object):
    """
    A proxy object wrapping a Python class and keeping timing information
    about method calls and submethod calls.
    """

    # static mapping of class names to ClassProfileData objects

    _cpdata = {}

    def __init__(self, subject):
        self._subject = subject
        self._classname = classname = subject.__class__.__name__
        if not ProfilingProxy._cpdata.has_key(classname):
            ProfilingProxy._cpdata[classname] = ClassProfileData(classname)

    def _profiledata(self):
        return ProfilingProxy._cpdata[self._classname]

    def __getattr__(self, name):
        subject = self._subject
        m = getattr(subject,name)
        if isinstance(m, MethodType):
            data = self._profiledata()
            def _callmethod(s, *args, **kw):
                data._push(name)
                now = time.time()
                r = m.im_func(s, *args, **kw)
                delta = time.time()-now
                data._pop_and_log(delta)

                return r
            r = new.instancemethod(_callmethod, self, subject.__class__)
            return r
 
        return m



if __name__ == '__main__':
    import random
    class foo:
        def __init__(self,initval=3):
            self.x = initval;
        def a(self):
            print "x = ",self.x
            for i in range(10):
                self.b()
                self.d()

        def b(self):
            self.x += 2
            time.sleep(0.1)
            pass

        def d(self):
            ch = random.choice((1,2,3,4,5))
            if ch<3:
                time.sleep(0.05)
            elif ch==5:
                return self.b()


        def c(self):
            print "x = ",self.x
            time.sleep(random.random()*0.3)


    o = ProfilingProxy(foo(3))
    o.a()
    p = ProfilingProxy(foo(12))
    p.a()

    o.c()
    p.c()

    data = o._profiledata()
    data.dumpflat()
    print ""
    data.dumptree()

    #import pprint
    #pprint.pprint(data.timestack)
