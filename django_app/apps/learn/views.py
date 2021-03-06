# -*- coding: utf-8 -*-
import datetime
import json
import logging
import re
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.urlresolvers import reverse
from django.db.models import Count, Q, Max
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.generic import View

from learn.models import WordBook, WordUnit, WordInUnit, LearningPlan, LearningRecord, ErrorWord, Word
from operations.models import GroupLearningPlan
from testings.models import QuizResult
from users.models import UserGroup, UserProfile, Group
from users.templatetags.user_info import is_teacher
from utils import lookup_word_in_db
from .tasks import do_add

logger = logging.getLogger(__name__)

class BookListView(View):
    def get(self, request):
        wordbooks = WordBook.objects.all()

        return render(request, 'wordbook_list.html', {
            "page": "books",
            "wordbooks": wordbooks
        })


def make_string_groups(m):
    """
    Taken a dict[str, object], return a tree.
    Example:

    strings = {
        "1 2 3 4": "first",
        "1 2 3 3": "second",
        "1 2 4 4": "third",
        "1 2 4 3": "fourth",
        "1 2": "fifth",
        "1 3 3": "sixth"
    }
    result = make_string_groups(strings)

    Now the result looks like:
    {
        "1": {
            "2": {
                "3": {
                    "3": "second",
                    "4": "first"
                },
                "4": {
                    "3": "fourth",
                    "4": "third"
                },
                "___": "fifth"
            },
            "3": {
                "3": "sixth"
            }
        }
    }

    :param dict[str, object] m: the map object which has key as '/' separated string
    :return tree
    """
    result = {}
    for k, v in m.items():
        container = result
        row = k.split('/')
        for folder in row[:-1]:
            if folder not in container:
                container[folder] = {}
            container = container[folder]
        final = row[-1]
        if final in container:
            container[final]["___"] = v
        else:
            container[row[-1]] = v
    return result


class AjaxBookTreeView(View):
    def get(self, request):
        wordbooks = WordBook.objects.all()
        wordbook_map = {}
        for book in wordbooks:
            wordbook_map[book.description] = {
                "description": book.description.split('/')[-1],
                "id": book.id
            }
        # construct a map
        book_tree = make_string_groups(wordbook_map)
        return JsonResponse({
            "status": "ok",
            "books": book_tree
        })


class AjaxBookListView(View):
    def get(self, request):
        wordbooks = WordBook.objects.order_by("description").values("id", "description").all()
        return JsonResponse({
            "status": "ok",
            "books": [x for x in wordbooks]
        })


class AjaxBookAddMaintainer(View):
    def post(self, request):
        book_id = request.POST.get("book_id")
        user_name = request.POST.get("user_name")
        try:
            maintainer = UserProfile.objects.filter(Q(email=user_name) | Q(mobile_phone=user_name)).get()
            book = WordBook.objects.filter(id=book_id).get()
            book.maintainers.add(maintainer)
            book.save()
        except:
            logger.exception("Failed to add maintainer")
            return JsonResponse({
                "status": "fail"
            })
        return JsonResponse({
            "status": "ok"
        })


class AjaxBookDeleteMaintainer(View):
    def post(self, request):
        book_id = request.POST.get("book_id")
        user_id = request.POST.get("user_id")
        try:
            book = WordBook.objects.filter(id=book_id).get()
            book.maintainers.remove(UserProfile.objects.get(id=user_id))
            book.save()
        except:
            return JsonResponse({
                "status": "fail"
            })
        return JsonResponse({
            "status": "ok"
        })


class AjaxBookUnitsView(View):
    def get(self, request, book_id):
        units = WordUnit.objects.filter(book_id=book_id).order_by("order").values("id", "description")
        return JsonResponse({
            "status": "ok",
            "units": [x for x in units]
        })


class AjaxNewBookView(LoginRequiredMixin, View):
    def post(self, request):
        description = request.POST.get("description", "")
        if description:
            # 是否重名？
            if WordBook.objects.filter(description=description).count():
                return JsonResponse({
                    "status": "fail",
                    "reason": "名为'{0}'的单词书已经存在了".format(description)
                })
            book = WordBook()
            book.description = description
            book.uploaded_by = request.user
            book.save()
            return JsonResponse({
                "status": "ok",
                "book_id": book.id
            })
        else:
            return JsonResponse({
                "status": "fail",
                "reason": "标题不对"
            })


class AjaxEditBookView(LoginRequiredMixin, View):
    def post(self, request):
        book_id = request.POST.get("book_id", 0)
        description = request.POST.get("description", "")

        try:
            if description:
                book = WordBook.objects.filter(id=book_id).get()
                book.description = description
                book.save()
                return JsonResponse({
                    "status": "ok"
                })
        except:
            pass

        return JsonResponse({
            "status": "fail",
            "reason": "输入不对"
        })


class AjaxDeleteBookView(LoginRequiredMixin, View):
    def post(self, request):
        book_id = request.POST.get("book_id", 0)
        WordBook.objects.filter(id=book_id).delete()
        return JsonResponse({
            "status": "ok"
        })


class AjaxNewUnitView(LoginRequiredMixin, View):
    def post(self, request):
        book_id = request.POST.get("book_id", 0)
        description = request.POST.get("description", "")

        try:
            if description:
                book = WordBook.objects.filter(id=book_id).get()
                max_order = WordUnit.objects.filter(book=book).aggregate(Max("order"))["order__max"]
                if not max_order:
                    max_order = 0
                unit = WordUnit()
                unit.book = book
                unit.description = description
                unit.order = max_order + 1
                unit.save()

                return JsonResponse({
                    "status": "ok",
                    "unit_id": unit.id
                })

        except:
            pass
        return JsonResponse({
            "status": "fail",
            "reason": "输入不对"
        })

def get_next_unit_name(name):
    regex = re.compile(r"(\D*)(\d+)(\D*)")
    m = regex.match(name)
    if m:
        index = int(m.group(2)) + 1
        return m.group(1) + str(index) + m.group(3)
    else:
        return name + "1"


class AjaxBatchAddUnitView(LoginRequiredMixin, View):
    def post(self, request):
        data = json.loads(request.body.decode("utf-8"))
        book_id = data.get('book_id', None)
        first_unit_name = data.get('first_unit_name', None)
        unit_size_limit = int(data.get('unit_size_limit', 20))
        text = data.get('text', "")

        failed_lines = []
        try:
            parsed_words = []

            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                good = False

                try:
                    parsed = parse_word_line(line)
                    if parsed:
                        parsed_words.append(parsed)
                        good = True
                except:
                    pass
                if not good:
                    failed_lines.append(line)
            # generate data to be added
            units_to_add = []
            unit_name = first_unit_name
            book = WordBook.objects.filter(id=book_id).get()
            max_order = WordUnit.objects.filter(book=book).aggregate(Max("order"))["order__max"]
            if not max_order:
                max_order = 0
            order = max_order + 1
            while len(parsed_words) > 0:
                words = parsed_words[:unit_size_limit]
                unit = {
                    'name': unit_name,
                    'order': order,
                    'words': words
                }
                units_to_add.append(unit)
                parsed_words = parsed_words[unit_size_limit:]
                unit_name = get_next_unit_name(unit_name)
                order += 1
            # now create the units
            for unit in units_to_add:
                wordunit = WordUnit()
                wordunit.book = book
                wordunit.description = unit['name']
                wordunit.order = unit['order']
                wordunit.save()
                # generate the words
                for word in unit['words']:
                    add_word_to_unit(wordunit.id, word['word'], word['meaning'])
            return JsonResponse({
                'status': 'ok',
                'failed_lines': failed_lines
            })
        except:
            logger.exception("Faled to add word")
            return JsonResponse({
                'status': 'fail'
            })


class AjaxEditUnitView(LoginRequiredMixin, View):
    def post(self, request):
        unit_id = request.POST.get("unit_id", 0)
        description = request.POST.get('description', "")
        order = request.POST.get("order", 0)
        try:
            if description:
                unit = WordUnit.objects.filter(id=unit_id).get()
                unit.description = description
                unit.order = int(order)
                unit.save()
                return JsonResponse({
                    "status": "ok"
                })
        except:
            pass
        return JsonResponse({
            "status": "fail",
            "reason": "输入不对"
        })


class AjaxDeleteUnitView(LoginRequiredMixin, View):
    def post(self, request):
        unit_id = request.POST.get("unit_id", 0)
        WordUnit.objects.filter(id=unit_id).delete()
        return JsonResponse({
            "status": "ok"
        })


def add_word_to_unit(unit_id, spelling, meaning, detailed_meaning=""):
    """
    把单词添加到单元里
    :param unit_id:
    :param spelling:
    :param meaning:
    :param detailed_meaning:
    :return:
    """
    unit = WordUnit.objects.filter(id=unit_id).get()

    # in case the word already exists
    if not WordInUnit.objects.filter(unit=unit, word__spelling=spelling).count():
        unit_word = WordInUnit()
        max_order = WordInUnit.objects.filter(unit=unit).aggregate(Max("order"))["order__max"]
        if not max_order:
            max_order = 0
        if spelling and meaning:
            # try to find the word first
            word = lookup_word_in_db.find_word(spelling)
            if not word:
                word = Word()
                word.spelling = spelling
                word.short_meaning = meaning
                word.detailed_meanings = "{}"
                word.save()

        unit_word.word = word
        unit_word.unit = unit
        unit_word.simple_meaning = meaning
        unit_word.detailed_meaning = detailed_meaning
        unit_word.order = max_order + 1
        unit_word.save()


class AjaxNewWordInUnitView(LoginRequiredMixin, View):
    def post(self, request):
        spelling = request.POST.get("spelling", "")
        meaning = request.POST.get("meaning", "")
        detailed_meaning = request.POST.get("detailed_meaning", "")
        unit_id = request.POST.get("unit_id", "")

        try:
            add_word_to_unit(unit_id, spelling, meaning, detailed_meaning)
            return JsonResponse({
                "status": "ok"
            })

        except:
            pass
        return JsonResponse({
            "status": "fail"
        })


line_word_re = re.compile("(.*)(\t| {4})(.*)")


def parse_word_line(line):
    m = line_word_re.match(line)
    if m:
        word = m.group(1).strip()
        meaning = m.group(3).strip()
        return {
            "word": word,
            "meaning": meaning
        }
    return None

class AjaxBatchInputWordView(LoginRequiredMixin, View):
    def post(self, request):
        data = json.loads(request.body.decode("utf-8"))
        unit_id = data.get('unit_id', None)
        text = data.get('text', '')

        if not unit_id or not text:
            return JsonResponse({
                "status": "fail"
            })
        failed_lines = []
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            good = False

            try:
                parsed = parse_word_line(line)

                if parsed:
                    word = parsed["word"]
                    meaning = parsed["meaning"]
                    add_word_to_unit(unit_id, word, meaning)
                    good = True
            except:
                pass
            if not good:
                failed_lines.append(line)

        return JsonResponse({
            "status": "ok",
            "failed_lines": failed_lines
        })


class AjaxDeleteWordInUnitView(LoginRequiredMixin, View):
    def post(self, request):
        unit_words = request.POST.get("unit_word_ids", "")
        words = unit_words.split(",")
        for id in words:
            WordInUnit.objects.filter(id=id).delete()
        return JsonResponse({
            "status": "ok"
        })


class BookDetailView(View):
    def get(self, request, book_id):
        wordbook = WordBook.objects.filter(id=book_id).get()
        if not wordbook:
            raise Http404()

        units = WordUnit.objects.filter(book_id=book_id).order_by("order").all()
        return render(request, 'wordbook_detail.html', {
            "page": "books",
            "book": wordbook,
            "units": units
        })


class LearningPlanView(LoginRequiredMixin, View):
    # list all units which are in the learning plan
    def get(self, request, user_id):
        my_plans = LearningPlan.objects.filter(user_id=user_id).values("unit_id").all()
        group_plans = GroupLearningPlan.objects.filter(group__usergroup__user_id=request.user.id).values("unit_id").all()

        all_planned_units = {}
        for u in my_plans:
            unit_id = u["unit_id"]
            all_planned_units[unit_id] = True
        for u in group_plans:
            unit_id = u["unit_id"]
            all_planned_units[unit_id] = True

        units = WordUnit.objects.filter(id__in=all_planned_units.keys()).all()
        for u in units:
            u.learn_times = u.learn_count(user_id)
            u.review_times = u.review_count(user_id)

        return render(request, 'unit_list.html', {
            "page": "units",
            "units": units
        })

def is_unit_in_plan(unit_id, user_id):
    """
    判断是否某个单元在某人的计划中
    :param int unit_id: unit id
    :param int user_id: user id
    :return:
    """
    if LearningPlan.objects.filter(unit_id=unit_id, user_id=user_id).count():
        return True
    # 有可能单元在班级计划里面
    if GroupLearningPlan.objects.filter(group__usergroup__user_id=user_id, unit_id=unit_id).count():
        return True

class UnitDetailView(View):
    def get(self, request, unit_id):
        unit = WordUnit.objects.filter(id=unit_id).get()
        if not unit:
            raise Http404()

        words = WordInUnit.objects.filter(unit=unit).order_by("order").all()

        is_planned = False
        records = None
        if request.user.is_authenticated():
            is_planned = is_unit_in_plan(unit_id, request.user.id)
            records = LearningRecord.objects.filter(unit_id=unit_id, user=request.user).all()
        return render(request, 'unit_detail.html', {
            "records": records,
            "page": "books",
            "unit": unit,
            "words": words,
            "is_planned": is_planned
        })


class UnitWordsTextView(View):
    def get(self, request, unit_id):
        unit = WordUnit.objects.filter(id=unit_id).get()
        if not unit:
            raise Http404()

        words = WordInUnit.objects.filter(unit=unit).order_by("order").all()
        result = ""
        for w in words:
            spelling = w.word.spelling
            meaning = w.simple_meaning
            line = "%-20s    %s\r\n" % (spelling, meaning)
            result += line
        return HttpResponse(result, **{"content_type": "application/text"})


class AjaxAddBookToLearningPlanView(LoginRequiredMixin, View):
    def post(self, request):
        book_id = request.POST.get("book_id", None)
        if not book_id:
            return JsonResponse({
                "status": "failure"
            })
        units = WordUnit.objects.filter(book_id=book_id).all()
        for unit in units:
            if not LearningPlan.objects.filter(unit=unit, user=request.user).count():
                plan = LearningPlan()
                plan.unit = unit
                plan.user = request.user
                plan.save()
        return JsonResponse({
            "status": "success"
        })


class AjaxAddUnitToLearningPlanView(LoginRequiredMixin, View):
    def post(self, request):
        unit_id = request.POST.get("unit_id", None)
        if not unit_id:
            return JsonResponse({
                "status": "failure"
            })
        if not LearningPlan.objects.filter(unit_id=unit_id, user=request.user).count():
            plan = LearningPlan()
            plan.unit_id = unit_id
            plan.user = request.user
            plan.save()
        return JsonResponse({
            "status": "success"
        })


class AjaxDeleteUnitFromLearningPlanView(LoginRequiredMixin, View):
    def post(self, request):
        unit_id = request.POST.get("unit_id", None)
        if not unit_id:
            return JsonResponse({
                "status": "failure"
            })
        LearningPlan.objects.filter(unit_id=unit_id, user=request.user).delete()
        return JsonResponse({
            "status": "success"
        })


class AjaxIsUnitInLearningPlan(LoginRequiredMixin, View):
    def get(self, request, unit_id):
        if LearningPlan.objects.filter(unit_id=unit_id, user=request.user).get():
            return JsonResponse({
                "result": "yes"
            })
        else:
            return JsonResponse({
                "result": "no"
            })


def get_active_units(user_id):
    """
    Get a list of active units for a given user.
    A unit is active if it meets any of the following criteria:
    - it has been learned at least once
    - it is in GroupLearningPlan
    :param int user_id: user id
    :return list: list of active units
    """
    active_units = {}
    learned_units = LearningRecord.objects.filter(user_id=user_id).values("unit_id").distinct().all()
    for u in learned_units:
        active_units[u["unit_id"]] = True
    user_groups = UserGroup.objects.filter(user_id=user_id, role__exact=1).all()
    today = datetime.date.today()
    for group in user_groups:
        group_units = GroupLearningPlan.objects.filter(start_date__lte=today,
                                                       start_date__gte=group.join_time,
                                                       group=group.group).values("unit_id",
                                                                           "start_date").distinct().all()
        for u in group_units:
            active_units[u["unit_id"]] = True
    all_active_units = active_units.keys()
    # if we have finished this unit, delete it
    result = [x for x in all_active_units if get_unit_learn_count(user_id, x) < 6]
    # if it's too small?
    if len(result) < 3:
        # the load for today is too small, try to add more units
        num_to_add = 3 - len(result)
        my_plan = LearningPlan.objects.filter(user_id=user_id).order_by("id").all()
        for p in my_plan:
            if not p.unit_id in all_active_units:
                result.append(p.unit_id)
                if len(result) >= 3:
                    break
    return {
        "all_active_units": all_active_units,
        "result": result
    }


def get_unit_learn_count(user_id, unit_id):
    """
    Get learning count for a given unit.
    :param int user_id: user id
    :param int unit_id: unit id
    :return int: learned count
    """
    return LearningRecord.objects.filter(user_id=user_id, unit_id=unit_id).count()


def has_learned_today(user_id, unit_id):
    """
    Determine whether a unit has been learned today
    :param int user_id: user id
    :param int unit_id: unit id
    :return bool: true if the unit has been learned today
    """
    return LearningRecord.objects.filter(user_id=user_id, unit_id=unit_id, learn_time__date=datetime.datetime.today()).count()


def is_unit_for_today(user_id, unit_id):
    """
    判断今天是不是需要学习某一个单元
    :param int user_id: user id
    :param int unit_id: unit id
    :return bool:
    """
    learn_count = get_unit_learn_count(user_id, unit_id)
    if learn_count > 5:
        return False
    if learn_count > 0:
        last_learn = LearningRecord \
            .objects\
            .filter(user_id=user_id, unit_id=unit_id)\
            .order_by("-learn_time").first()
        today = datetime.datetime.today().date()
        last_learned_date = last_learn.learn_time.date()
        delta = today - last_learned_date
        # 计算最后一次学习距离今天有多少天
        delta_days = delta.days
        learning_curve = [1, 1, 2, 3, 8]
        if delta_days >= learning_curve[learn_count - 1]:
            return True
    return True


def get_todays_units(user_id):
    """
    Get list of today's pending units
    :param int user_id:
    :return list: list of unit ids for today's learning
    """
    active_units = get_active_units(user_id)["result"]
    result = [x for x in active_units if not has_learned_today(user_id, x) and is_unit_for_today(user_id, x)]
    return result[:5]


class StartLearnView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'learn_start.html', {
            'user': request.user
        })


class AjaxGetTodayUnitsView(LoginRequiredMixin, View):
    def get(self, request):
        units = get_todays_units(request.user.id)
        return JsonResponse({
            "status": "ok",
            "units": units
        })


class LearningOverviewView(LoginRequiredMixin, View):
    def get_for_student(self, request):
        learn_count = LearningRecord.objects.filter(user=request.user).count()
        quiz_count = QuizResult.objects.filter(user=request.user).count()
        erroneous_words = ErrorWord.objects.filter(user=request.user, amend_count__lt=2).count()
        # get recent learned units

        active_units = get_active_units(request.user.id)
        today_units = get_todays_units(request.user.id)
        recent_units = []
        for u in active_units["result"]:
            unit = WordUnit.objects.get(id=u)
            obj = {
                'unit_id': unit.id,
                'unit__book_id': unit.book.id,
                'unit__book__description': unit.book.description,
                'unit__description': unit.description,
                'learn_count': get_unit_learn_count(request.user.id, unit.id)
            }
            recent_units.append(obj)
        recent_units = sorted(recent_units, key=lambda x: x['learn_count'])

        # try to get progress for the units
        for u in recent_units:
            count = int(u["learn_count"])
            if count > 5:
                u["progress"] = 100
            else:
                u["progress"] = int(100 * count / 6)
        mastered_unit_count = len(active_units["all_active_units"]) - len(active_units["result"])

        groups = Group.objects.filter(usergroup__user=request.user).all()
        return render(request, 'index.html', {
            "page": "overview",
            "learn_count": learn_count,
            "quiz_count": quiz_count,
            "erroneous_words": erroneous_words,
            "today_units": today_units,
            "recent_units": recent_units[:10],
            "mastered_unit_count": mastered_unit_count,
            "groups": groups
        })

    def get_for_teacher(self, request):
        return redirect(reverse('user.my_groups'))

    def get(self, request):
        if is_teacher(request.user.id):
            return self.get_for_teacher(request)
        else:
            return self.get_for_student(request)


class LearningView(LoginRequiredMixin, View):
    def get(self, request, user_id):
        user = UserProfile.objects.filter(id=user_id).get()
        records = LearningRecord.objects.filter(user=user).order_by("-learn_time").all()
        # 取得最近一个月学习记录
        today = datetime.date.today()
        recent_learning_times = []
        for i in range(30):
            d = today - datetime.timedelta(days=29-i)
            count = LearningRecord.objects.filter(user=user, learn_time__year = d.year,
                                                  learn_time__month=d.month,
                                                  learn_time__day=d.day).count()
            recent_learning_times.append({
                "date": d.isoformat(),
                "count": count
            })

        # 获取最近学习过的10个单元
        recent_units = LearningRecord\
            .objects\
            .filter(user=user) \
            .values('unit_id', "unit__description").distinct()\
            .annotate(recent_learn_time=Max("learn_time")).order_by("-recent_learn_time")[:10]
        # 获取每个单元里面的错词
        error_table = []
        for u in recent_units:
            unit_id = u['unit_id']
            error_words = ErrorWord.objects.filter(user_id=user.id, word__unit_id=unit_id).values('word_id', 'word__word__spelling', 'word__simple_meaning').distinct()
            error_table.append({
                "unit_id": unit_id,
                "unit_title": u["unit__description"],
                "error_words": [{
                    "id": x["word_id"],
                    "spelling": x["word__word__spelling"],
                    "meaning": x["word__simple_meaning"]
                } for x in error_words]
            })

            # 计算最近单元的百分比
            active_units = get_active_units(user_id)
            recent_units = []
            for u in active_units["result"]:
                unit = WordUnit.objects.get(id=u)
                obj = {
                    'unit_id': unit.id,
                    'unit__book_id': unit.book.id,
                    'unit__book__description': unit.book.description,
                    'unit__description': unit.description,
                    'learn_count': get_unit_learn_count(user_id, unit.id)
                }
                recent_units.append(obj)
            recent_units = sorted(recent_units, key=lambda x: x['learn_count'])

            # try to get progress for the units
            for u in recent_units:
                count = int(u["learn_count"])
                if count > 5:
                    u["progress"] = 100
                else:
                    u["progress"] = int(100 * count / 6)
        return render(request, 'learn_records.html', {
            "user": user,
            "recent_records": recent_learning_times,
            "page": "learning",
            "recent_units": recent_units[:10],
            "recent_error_records": error_table
        })


class ReviewView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'todo.html', {
            "page": "review"
        })


class AjaxUnitDataView(LoginRequiredMixin, View):
    def get(self, request, unit_id):
        words_in_unit = WordInUnit.objects.filter(unit_id=unit_id).order_by("order").all()
        if not words_in_unit:
            return JsonResponse({
                "status": "failure"
            })
        result = []
        for w in words_in_unit:
            detailed_meaning = {}
            if w.word.detailed_meanings:
                detailed_meaning = json.loads(w.word.detailed_meanings)
            result.append({
                "id": w.id,
                "simple_meaning": w.simple_meaning,
                "detailed_meaning": w.detailed_meaning,
                "spelling": w.word.spelling,
                "pronounciation_us": w.word.pronounciation_us,
                "pronounciation_uk": w.word.pronounciation_uk,
                "mp3_us_url": w.word.mp3_us_url,
                "mp3_uk_url": w.word.mp3_uk_url,
                "short_meaning_in_dict": w.word.short_meaning,
                "detailed_meaning_in_dict": detailed_meaning
            })
        return JsonResponse({
            "data": result,
            "learn_count": get_unit_learn_count(request.user.id, unit_id)
        })


class UnitWalkThroughView(LoginRequiredMixin, View):
    def get(self, request, unit_id):
        try:
            unit = WordUnit.objects.filter(id=unit_id).get()
            return render(request, 'unit_walkthrough.html', {
                "page": "learning",
                "unit": unit
            })
        except KeyError:
            raise Http404()


class UnitLearnView(LoginRequiredMixin, View):
    def get(self, request, unit_id):
        try:
            unit = WordUnit.objects.filter(id=unit_id).get()
            return render(request, 'unit_learn.html', {
                "page": "learning",
                "unit": unit,
                "page_title": u"单元学习",
                "type": 1,
                "data_url": reverse('learn.ajax_unit_data', kwargs={"unit_id": unit_id}),
                "save_url": reverse('learn.save_record')
            })
        except:
            raise Http404()


class UnitTestView(LoginRequiredMixin, View):
    def get(self, request, unit_id):
        try:
            unit = WordUnit.objects.filter(id=unit_id).get()
            return render(request, 'unit_spelling_test.html', {
                "page": "learning",
                "unit": unit,
                "page_title": u"单元测试",
                "type": 2,
                "data_url": reverse('learn.ajax_unit_data', kwargs={"unit_id": unit_id}),
                "save_url": reverse('learn.save_record')
            })
        except:
            raise Http404()


class AjaxSaveLearnRecordView(LoginRequiredMixin, View):
    def post(self, request):
        data = json.loads(request.body.decode("utf-8"))
        unit_id = data.get("unit_id", None)
        type = data.get("type", None)
        correct_rate = data.get("correct_rate", 0)
        seconds_used = data.get("seconds_used", 0)

        if not unit_id or not type:
            return JsonResponse({
                "status": "fail"
            })
        try:
            unit = WordUnit.objects.filter(id=unit_id).get()
            record = LearningRecord()
            record.user = request.user
            record.unit = unit
            record.type = type
            record.correct_rate = correct_rate
            record.duration = seconds_used
            record.save()
            if "error_words" in data:
                error_words = data["error_words"]
                for w in error_words:
                    error_records = ErrorWord.objects.filter(user=request.user, word_id=w).all()
                    if len(error_records):
                        error_record = error_records[0]
                    else:
                        error_record = ErrorWord()
                    error_record.user = request.user
                    error_record.word_id = w
                    error_record.error_count += 1
                    error_record.latest_error_time = datetime.datetime.now()
                    error_record.save()
            return JsonResponse({
                "status": "success"
            })
        except:
            return JsonResponse({
                "status": "fail"
            })


class UnitReviewView(LoginRequiredMixin, View):
    def get(self, request, unit_id):
        try:
            unit = WordUnit.objects.filter(id=unit_id).get()
            return render(request, 'unit_learn.html', {
                "page": "learning",
                "unit": unit,
                "type": 3,
                "page_title": u"单元复习",
                "data_url": reverse('learn.ajax_unit_data', kwargs={"unit_id": unit_id}),
                "save_url": reverse('learn.save_record')
            })
        except KeyError:
            raise Http404()


class ErrorWordListView(LoginRequiredMixin, View):
    def get(self, request):
        error_words = ErrorWord.objects.filter(user=request.user).order_by("-latest_error_time").all()
        return render(request, "error_word_list.html", {
            "page": "error_words",
            "error_words": error_words
        })


class ErrorWordTextView(LoginRequiredMixin, View):
    def get(self, request):
        error_words = ErrorWord.objects.filter(user=request.user).order_by("-latest_error_time").all()
        result = ""
        for e in error_words:
            spelling = e.word.word.spelling
            meaning = e.word.simple_meaning
            line = "%-20s  %s\r\n" % (spelling, meaning)
            result += line
        return HttpResponse(result, **{"content_type": "application/text"})


class AmendErrorWordView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'unit_learn.html', {
            "page": "learning",
            "page_title": u"错词重测",
            "type": 2,
            "data_url": reverse('learn.ajax_error_words'),
            "save_url": reverse('learn.ajax_amend_error_words')
        })


class AjaxErrorWordsView(LoginRequiredMixin, View):
    def get(self, request):
        error_words = ErrorWord.objects.filter(user=request.user, amend_count__lt=2).order_by("-latest_error_time").all()
        result = []
        for error_word in error_words:
            w = error_word.word
            detailed_meaning = {}
            if w.word.detailed_meanings:
                detailed_meaning = json.loads(w.word.detailed_meanings)
            result.append({
                "id": w.id,
                "simple_meaning": w.simple_meaning,
                "detailed_meaning": w.detailed_meaning,
                "spelling": w.word.spelling,
                "pronounciation_us": w.word.pronounciation_us,
                "pronounciation_uk": w.word.pronounciation_uk,
                "mp3_us_url": w.word.mp3_us_url,
                "mp3_uk_url": w.word.mp3_uk_url,
                "short_meaning_in_dict": w.word.short_meaning,
                "detailed_meaning_in_dict": detailed_meaning
            })
        return JsonResponse({
            "data": result
        })


class AjaxAmendErrorWordsView(LoginRequiredMixin, View):
    def post(self, request):
        data = json.loads(request.body.decode("utf-8"))
        if "correct_words" in data:
            for wid in data["correct_words"]:
                error_record = ErrorWord.objects.filter(user=request.user, word_id=wid).get()
                error_record.amend_count += 1
                error_record.save()
        if "error_words" in data:
            for wid in data["error_words"]:
                error_record = ErrorWord.objects.filter(user=request.user, word_id=wid).get()
                error_record.error_count += 1
                error_record.latest_error_time = datetime.datetime.now()
                error_record.save()
        return JsonResponse({
            "status": "success"
        })
