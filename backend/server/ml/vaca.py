import hashlib
import os
import pickle
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from urllib.parse import urlencode

import requests
from tqdm import tqdm

CACHE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "cache")


class DataCollector:
    __API_BASE_URL = "https://api.hh.ru/vacancies/"
    __DICT_KEYS = (
        "Ids",
        "Employer",
        "Name",
        "Salary",
        "From",
        "To",
        "Experience",
        "Schedule",
        "Keys",
        "Description",
    )

    def __init__(self, exchange_rates: Optional[Dict]):
        self._rates = exchange_rates

    @staticmethod
    def clean_tags(html_text: str) -> str:

        pattern = re.compile("<.*?>")
        return re.sub(pattern, "", html_text)

    @staticmethod
    def __convert_gross(is_gross: bool) -> float:
        return 0.87 if is_gross else 1

    def get_vacancy(self, vacancy_id: str):
        url = f"{self.__API_BASE_URL}{vacancy_id}"
        vacancy = requests.get(url).json()

        salary = vacancy.get("salary")

        from_to = {"from": None, "to": None}
        if salary:
            is_gross = vacancy["salary"].get("gross")
            for k, v in from_to.items():
                if vacancy["salary"][k] is not None:
                    _value = self.__convert_gross(is_gross)
                    from_to[k] = int(_value * salary[k] / self._rates[salary["currency"]])

        return (
            vacancy_id,
            vacancy.get("name", ""),
            vacancy.get("employer", {}).get("name", ""),
            salary is not None,
            from_to["from"],
            from_to["to"],
            vacancy.get("experience", {}).get("name", ""),
            vacancy.get("schedule", {}).get("name", ""),
            [el["name"] for el in vacancy.get("key_skills", [])],
            self.clean_tags(vacancy.get("description", "")),
        )

    @staticmethod
    def __encode_query_for_url(query: Optional[Dict]) -> str:
        if 'professional_roles' in query:
            query_copy = query.copy()

            roles = '&'.join([f'professional_role={r}' for r in query_copy.pop('professional_roles')])

            return roles + (f'&{urlencode(query_copy)}' if len(query_copy) > 0 else '')

        return urlencode(query)

    def collect_vacancies(self, query: Optional[Dict], refresh: bool = False, num_workers: int = 1) -> Dict:

        if num_workers is None or num_workers < 1:
            num_workers = 1

        url_params = self.__encode_query_for_url(query)

        cache_name: str = url_params
        cache_hash = hashlib.md5(cache_name.encode()).hexdigest()
        cache_file = os.path.join(CACHE_DIR, cache_hash)
        try:
            if not refresh:
                print(f"[INFO]: Get results from cache! Enable refresh option to update results.")
                return pickle.load(open(cache_file, "rb"))
        except (FileNotFoundError, pickle.UnpicklingError):
            pass

        target_url = self.__API_BASE_URL + "?" + url_params
        num_pages = requests.get(target_url).json()["pages"]

        ids = []
        for idx in range(num_pages + 1):
            response = requests.get(target_url, {"page": idx})
            data = response.json()
            if "items" not in data:
                break
            ids.extend(x["id"] for x in data["items"])

        jobs_list = []
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            for vacancy in tqdm(
                    executor.map(self.get_vacancy, ids),
                    desc="Get data via HH API",
                    ncols=100,
                    total=len(ids),
            ):
                jobs_list.append(vacancy)

        unzipped_list = list(zip(*jobs_list))

        result = {}
        for idx, key in enumerate(self.__DICT_KEYS):
            result[key] = unzipped_list[idx]

        pickle.dump(result, open(cache_file, "wb"))
        return result

    def get_vacancy_by_url(self, url: str):
        match = re.search(r"/vacancy/(d+)", url)

        if match:
            vacancy_id = match.group(1)
        else:
            raise ValueError(f"Could not extract the vacancy ID from the URL: {url}")

        return self.get_vacancy(vacancy_id)





# @celery.task
# def get_dict(url):
#     dc = DataCollector(exchange_rates={"USD": 0.01264, "EUR": 0.01083, "RUR": 1.00000})
#     def F(url):
#         start = url.rfind('/') + 1
#         end = url.find('?')
#         number = url[start:end]
#         return number
#     keys = ['Ids', 'Name', 'Employer', 'VacancyOpen', 'Salary', 'Currency', 'Experience',
#             'Schedule', 'Keys', 'Description']
#     job_dict = dict(zip(keys, dc.get_vacancy(F(url))))
#     return job_dict
